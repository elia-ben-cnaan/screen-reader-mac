#!/usr/bin/env python3
"""Does the on-screen simplification say the same as the statement? For every SELF_REPORT bank item:
send its text + options to a proxy (as OCR text), take PLAIN, then ask a separate judge model whether PLAIN asks
the same thing as the ORIGINAL statement (same behaviour, same direction/negation, nothing dropped, fits the
response format). The bank's plain_meaning is NOT used as the reference: it is one sentence shared by a whole
family, so it leaves out the conditions each variant adds. Also reports PLAIN length and qualifier keeping.
Usage: fidelity.py <port> [limit] [--out file.jsonl] [--ids SR-001,SR-007]
limit N < 300 takes N items spread over all families and all 5 variants. Each item = 1 proxy request + 1 judge call."""
import json, os, re, sys, statistics, urllib.request
from concurrent.futures import ThreadPoolExecutor
port = sys.argv[1]; limit = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 0
out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
C = os.path.expanduser("~/.config/screenreader")
tok = open(f"{C}/client_token").read().strip(); key = open(f"{C}/llm_key").read().strip()
bank = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bank.json")))
ids = set(sys.argv[sys.argv.index("--ids") + 1].split(",")) if "--ids" in sys.argv else None
if ids: bank = [b for b in bank if b["id"] in ids]
elif limit and limit < len(bank):   # family i -> its variant i%5, so every variant is covered equally
    fam = [bank[i:i + 5] for i in range(0, len(bank), 5)]
    step = max(1, len(fam) // limit)
    bank = [f[(i // step) % 5] for i, f in enumerate(fam) if i % step == 0][:limit] if limit <= len(fam) else bank[:limit]
QUAL = ["לפעמים", "תמיד", "בדרך כלל", "מעולם", "אף פעם", "לעיתים", "רק"]

def ask(it):
    text = it["text"] + "\n" + "   ".join(it["options"])
    r = urllib.request.Request(f"http://127.0.0.1:{port}/ask", data=json.dumps({"text": text}).encode(), headers={"X-Token": tok})
    rep = urllib.request.urlopen(r, timeout=120).read().decode()
    f = {l.split(":", 1)[0].strip(): l.split(":", 1)[1].strip() for l in rep.splitlines() if ":" in l}
    return f

def judge(it, plain):
    q = (f"Original statement (Hebrew personality/integrity questionnaire): {it['text']}\nResponse options on screen: {' | '.join(it['options'])}\n"
         f"Simplified version shown to a weak reader: {plain}\n\n"
         "The reader sees only the simplified version and the options. Check three things:\n"
         "1 MEANING: same behaviour/attitude and same direction as the original after resolving its negations "
         "(\"לא נכון לומר שמעולם לא היה מצב שבו X\" means \"it has happened that X\" = \"קרה ש-X\" / \"יש מצבים ש-X\"; it does NOT mean X is usual).\n"
         "2 KEPT: every condition, reason, comparison, object and frequency/quantity word of the original is still there "
         "(a plain synonym is fine; a missing condition is not).\n"
         "3 FORMAT: the options answer it directly — a first-person statement for agreement or true-for-me options, "
         "\"באיזו תדירות\" for a frequency scale, \"האם\" for yes/no; choosing the same option must mean the same as in the original.\n"
         "Reply on one line: SAME or DIFFERENT, then a dash, then which check failed (meaning / kept / format) and max 10 words why.")
    body = {"contents": [{"role": "user", "parts": [{"text": q}]}], "generationConfig": {"maxOutputTokens": 400, "thinkingConfig": {"thinkingBudget": 512}}}
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
