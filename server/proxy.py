#!/usr/bin/env python3
"""ScreenReader tutor proxy: Mac app -> this server -> cheap model (Gemini Flash). Key stays here.

POST /ask  header X-Token: <client token>   body {"text": "...", "image": "<base64 png>|null"}
Response: text/plain, streamed as the model writes it.
Config (/root/.config/screenreader/): llm_key (Gemini API key), client_token (shared with the app).
"""
import json, os, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONF = os.path.expanduser("~/.config/screenreader")
PORT = int(os.environ.get("SR_PORT", "8099"))
MODEL = os.environ.get("SR_MODEL", "gemini-flash-latest")
PROMPT = ("You solve practice-simulator questions shown on screen. Input: noisy OCR text of the whole screen "
          "(Hebrew or English) and, for visual questions, a cropped image of the question and options (shapes, "
          "matrices, sequences). Find the one active question and answer it. NO explanations. Reply in the "
          "question's language with exactly three lines:\n"
          "ANSWER: <option label as shown on screen, e.g. א/ב/ג/ד or A/B/C/D; '-' if there are no options>\n"
          "Q: <the question, cleaned, at most 20 words>\n"
          "A: <the answer itself, at most 4 words, e.g. '5 שעות' or 'הרביעית'>")


def read(name):
    try:
        return open(os.path.join(CONF, name)).read().strip()
    except OSError:
        return ""


def gemini_stream(key, text, image):
    parts = [{"text": "OCR text:\n" + text}]
    if image:
        parts.insert(0, {"inline_data": {"mime_type": "image/png", "data": image}})
    body = {"system_instruction": {"parts": [{"text": PROMPT}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"maxOutputTokens": 200, "thinkingConfig": {"thinkingBudget": 512}}}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:streamGenerateContent?alt=sse",
        data=json.dumps(body).encode(), headers={"content-type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=60) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data:"):
                continue
            j = json.loads(line[5:])
            for c in j.get("candidates", []):
                for p in c.get("content", {}).get("parts", []):
                    if p.get("text") and not p.get("thought"):
                        yield p["text"]


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.reply(200, "ok" if read("llm_key") else "no key")

    def do_POST(self):
        token = read("client_token")
        if self.path != "/ask" or not token or self.headers.get("X-Token") != token:
            return self.reply(403, "forbidden")
        key = read("llm_key")
        if not key:
            return self.reply(503, "Server has no model key yet (~/.config/screenreader/llm_key).")
        try:
            q = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))
        except ValueError:
            return self.reply(400, "bad json")
        self.send_response(200)
        self.send_header("content-type", "text/plain; charset=utf-8")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        try:
            for t in gemini_stream(key, q.get("text", ""), q.get("image")):
                self.chunk(t)
        except urllib.error.HTTPError as e:
            self.chunk(f"\nModel error {e.code}: {e.read().decode()[:300]}")
        except Exception as e:
            self.chunk(f"\nModel error: {e}")
        self.wfile.write(b"0\r\n\r\n")

    def chunk(self, s):
        b = s.encode()
        self.wfile.write(b"%x\r\n%s\r\n" % (len(b), b)); self.wfile.flush()

    def reply(self, code, msg):
        b = msg.encode()
        self.send_response(code)
        self.send_header("content-type", "text/plain; charset=utf-8")
        self.send_header("content-length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def log_message(self, *a):  # no question text in logs
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
