#!/usr/bin/env python3
"""ScreenReader proxy: Mac app -> this server -> cheap model (Gemini Flash). Key stays here.

POST /ask  header X-Token: <client token>
  body {"text": "<OCR>", "image": "<base64 png>|null", "context": "<unit instructions / passage so far>"}
Response: text/plain lines (format in PROMPT). If the fast model is unsure, a stronger model re-checks;
"CHECKING" is sent first so the app can show it.
Config (/root/.config/screenreader/): llm_key (Gemini API key), client_token (shared with the app).
"""
import json, os, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONF = os.path.expanduser("~/.config/screenreader")
PORT = int(os.environ.get("SR_PORT", "8099"))
FAST = os.environ.get("SR_MODELS", "gemini-flash-latest,gemini-flash-lite-latest,gemini-3.8-flash").split(",")
STRONG = os.environ.get("SR_STRONG", "gemini-pro-latest,gemini-3.8-flash").split(",")

GUIDE = """How to solve each kind (use the unit instructions in CONTEXT when present — they define the rules):
- Analogies: find the exact relation in the given pair (part-whole, cause, degree, tool-use...), pick the option with the same relation in the same direction.
- Sentence completion: choose the words that keep the sentence's logic (contrast words like אבל/למרות flip the meaning).
- Reading comprehension: answer only from the passage in CONTEXT/screen, not world knowledge.
- Word problems / quantitative: set up the equation, compute exactly, match units and the option.
- Number/letter sequences: test differences, second differences, ratios, alternating sequences, positions.
- Matrices (3x3 shapes): find the rule per row AND per column (shape, count, rotation, fill, add/subtract); the missing cell must satisfy both.
- Odd one out / shapes: find the property all share except one (sides, symmetry, rotation, count, fill).
- Graphs and tables: read exact values from the image, compute what is asked (difference, ratio, percent change).
- Logic: test each option against every condition; eliminate."""

PROMPT = """You assist with a multiple-choice practice simulator (Hebrew or English). Input: noisy OCR of the captured screen, sometimes an image of it, and CONTEXT = instructions of the current unit (and a reading passage) seen earlier.
First classify the screen:
- INSTRUCTIONS: a unit/section intro explaining the question type or rules (no answer options to choose).
- QUESTION: one active question with answer options.
- OTHER: anything else (menu, loading, score, unrelated app).
Reply with these lines only, no extra text. Write every value (Q, A, WHY, UNIT, SUMMARY) in the same language as the question on screen:
For QUESTION:
ANSWER: <option label exactly as on screen, e.g. א/ב/ג/ד or 1/2/3/4>
KIND: question
NUM: <question number if visible, else ->
Q: <the question, cleaned, max 20 words>
A: <the answer itself, max 4 words>
WHY: <one short line, the key step, max 12 words>
CONF: <high or low — low if the OCR/image is unclear or you are unsure>
For INSTRUCTIONS:
KIND: instructions
UNIT: <unit name, 1-3 words, e.g. אנלוגיות>
NUM: <unit number if visible, else ->
SUMMARY: <what to do in this unit, one sentence>
VISUAL: <yes if questions in this unit are shapes/matrices/graphs, else no>
PASSAGE: <yes if this screen is a reading passage for following questions, else no>
For OTHER:
KIND: other

""" + GUIDE


def read(name):
    try:
        return open(os.path.join(CONF, name)).read().strip()
    except OSError:
        return ""


def gemini(key, model, text, image, context, strong=False):
    parts = []
    if image:
        parts.append({"inline_data": {"mime_type": "image/png", "data": image}})
    parts.append({"text": (f"CONTEXT:\n{context}\n\n" if context else "") + "SCREEN OCR:\n" + text})
    gen = {"maxOutputTokens": 2500 if not strong else 6000}
    if not strong:
        gen["thinkingConfig"] = {"thinkingBudget": 1024}
    body = {"system_instruction": {"parts": [{"text": PROMPT}]},
            "contents": [{"role": "user", "parts": parts}], "generationConfig": gen}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode(), headers={"content-type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=12 if not strong else 40) as r:
        j = json.load(r)
    return "".join(p.get("text", "") for c in j.get("candidates", [])
                   for p in c.get("content", {}).get("parts", []) if not p.get("thought")).strip()


def first_ok(key, models, *a, **kw):
    """Busy/quota/unknown model -> next model. Returns (text, error)."""
    err = ""
    for m in models:
        try:
            out = gemini(key, m, *a, **kw)
            if out:
                return out, ""
        except urllib.error.HTTPError as e:
            err = f"Model error {e.code}: {e.read().decode()[:200]}"
            if e.code not in (400, 404, 429, 500, 503):
                break
        except Exception as e:
            err = f"Model error: {e}"
    return "", err


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

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
        args = (q.get("text", ""), q.get("image"), q.get("context", ""))
        self.send_response(200)
        self.send_header("content-type", "text/plain; charset=utf-8")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        out, err = first_ok(key, FAST, *args)
        if out and "KIND: question" in out and "CONF: low" in out:
            self.chunk("CHECKING\n")                      # app shows "בודק שוב…"
            better, _ = first_ok(key, STRONG, *args, strong=True)
            if better and "ANSWER:" in better:
                out = better
        self.chunk(out or err)
        self.wfile.write(b"0\r\n\r\n"); self.wfile.flush()

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
