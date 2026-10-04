#!/usr/bin/env python3
"""Does the on-screen simplification say the same as the statement? For every SELF_REPORT bank item:
send its text + options to a proxy (as OCR text), take PLAIN, then ask a separate judge model whether PLAIN asks
the same thing as the dataset's plain meaning (same behaviour, same direction/negation, same qualifiers, same
frame: agreement / frequency / yes-no). Also reports PLAIN length and qualifier keeping.
Usage: fidelity.py <port> [limit] [--out file.jsonl]"""
import json, os, re, sys, statistics, urllib.request
from concurrent.futures import ThreadPoolExecutor
port = sys.argv[1]; limit = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 0
out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
C = os.path.expanduser("~/.config/screenreader")
tok = open(f"{C}/client_token").read().strip(); key = open(f"{C}/llm_key").read().strip()
bank = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bank.json")))
if limit: bank = bank[::max(1, len(bank) // limit)][:limit]
QUAL = ["לפעמים", "תמיד", "בדרך כלל", "מעולם", "אף פעם", "לעיתים", "רק"]

def ask(it):
    text = it["text"] + "\n" + "   ".join(it["options"])
    r = urllib.request.Request(f"http://127.0.0.1:{port}/ask", data=json.dumps({"text": text}).encode(), headers={"X-Token": tok})
    rep = urllib.request.urlopen(r, timeout=120).read().decode()
    f = {l.split(":", 1)[0].strip(): l.split(":", 1)[1].strip() for l in rep.splitlines() if ":" in l}
    return f

def judge(it, plain):
    q = (f"Original statement (Hebrew questionnaire): {it['text']}\nResponse format: {' | '.join(it['options'])}\n"
         f"Reference meaning: {it['plain_meaning']}\nSimplified version shown to the reader: {plain}\n\n"
         "Would a reader who only reads the simplified version understand exactly what the original asks — same behaviour, "
         "same direction (positive/negative, double negation resolved correctly), same qualifiers (always/sometimes/never/only/"
         "without permission), and a question that fits the response format? Reply with one word: SAME or DIFFERENT, then a dash and max 10 words why.")
    body = {"contents": [{"role": "user", "parts": [{"text": q}]}], "generationConfig": {"maxOutputTokens": 400, "thinkingConfig": {"thinkingBudget": 256}}}
    r = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent",
                               data=json.dumps(body).encode(), headers={"content-type": "application/json", "x-goog-api-key": key})
    j = json.load(urllib.request.urlopen(r, timeout=60))
    return "".join(p.get("text", "") for c in j.get("candidates", []) for p in c["content"]["parts"] if not p.get("thought")).strip()

def one(it):
    try:
        f = ask(it); plain = f.get("PLAIN", "")
        v = judge(it, plain) if plain else "DIFFERENT - no PLAIN"
    except Exception as e:
        f, plain, v = {}, "", f"ERROR - {e}"
    stmt = it["text"].replace("לא נכון לומר שמעולם לא היה מצב", "") if it["challenge_tag"] == "double_negation" else it["text"]
    lost = [w for w in QUAL if re.search(rf"(^|\s|ש|ו|כ|ב|ה){w}(\s|$|[?,.])", stmt) and w not in plain]
    return {"id": it["id"], "tag": it["challenge_tag"], "plain": plain, "key": f.get("KEY", ""), "words": len(plain.split()),
            "same": v.upper().startswith("SAME"), "verdict": v, "lost": lost, "kind": f.get("KIND", "")}

with ThreadPoolExecutor(4) as ex: res = list(ex.map(one, bank))
if out: open(out, "w").write("\n".join(json.dumps(r, ensure_ascii=False) for r in res))
n = len(res); same = sum(r["same"] for r in res)
print(f"FIDELITY {same}/{n} ({100*same//n}%) · qualifier lost {sum(bool(r['lost']) for r in res)} · not self_report {sum(r['kind']!='self_report' for r in res)}")
w = [r["words"] for r in res if r["plain"]]
print(f"WORDS avg {statistics.mean(w):.1f} · median {statistics.median(w)} · max {max(w)} · over 10: {sum(x > 10 for x in w)}")
for t in ["baseline", "frequency", "question", "double_negation", "contextual"]:
    rs = [r for r in res if r["tag"] == t]
    if rs: print(f"  {t:16} {sum(r['same'] for r in rs)}/{len(rs)}")
for r in res:
    if not r["same"] or r["lost"]: print(f"  {r['id']} {r['tag']}: {r['plain']}  ← {r['verdict'][:90]} {r['lost'] or ''}")
