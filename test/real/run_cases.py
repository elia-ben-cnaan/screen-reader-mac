#!/usr/bin/env python3
"""Replay OCR-text screens against a proxy and score them by type.
Usage: run_cases.py [port] [cases.json] [repeats] [--ids T01,Q02] [--jobs 3] [--out results.jsonl]
Default cases file: adversarial.json next to this script (rules_tf.json works too; items without "type" count as rules).

Case fields: id, type, text, and per type:
  rules / quant / seq / analogy / question_trap : expected = option label the model must return (KIND question)
  format        : format = typed|order|multi, expected = answer (order compared as a sequence, multi as a set)
  instructions  : optional passage = yes|no
  other         : KIND must be other
  self_report   : options = exact on-screen options, neg = yes|no, require = words that must appear in PLAIN;
                  ANSWER must be empty, PLAIN must not keep "לא נכון לומר" or hint at an answer."""
import json, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

args = [a for a in sys.argv[1:] if not a.startswith("--")]
opt = {a.split("=")[0]: (a.split("=", 1)[1] if "=" in a else sys.argv[sys.argv.index(a) + 1]) for a in sys.argv[1:] if a.startswith("--")}
port = args[0] if args else "8099"
path = args[1] if len(args) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "adversarial.json")
reps = int(args[2]) if len(args) > 2 else 1
only = set(opt["--ids"].split(",")) if "--ids" in opt else None
jobs = int(opt.get("--jobs", 3))
tok = open(os.path.expanduser("~/.config/screenreader/client_token")).read().strip()
cases = [c for c in json.load(open(path)) if not only or c["id"] in only]
NO_HINT = ["מומלץ", "כדאי לבחור", "התשובה הנכונה", "עדיף לענות", "כדאי לסמן"]
QUESTION_TYPES = ("rules", "quant", "seq", "analogy", "question_trap")


def ask(text):
    r = urllib.request.Request(f"http://127.0.0.1:{port}/ask", data=json.dumps({"text": text}).encode(), headers={"X-Token": tok})
    t0 = time.time()
    out = urllib.request.urlopen(r, timeout=180).read().decode()
    return out, int((time.time() - t0) * 1000)


def fields(out):
    f = {}
    for l in out.splitlines():
        if ":" in l and not l.startswith("CHECKING"):
            k, v = l.split(":", 1); f[k.strip().upper()] = v.strip()
    return f


def norm_fmt(fmt, a):
    a = re.sub(r"\s+", "", a).replace("<-", "←").replace("->", "←").strip(".")
    if fmt == "multi": return "+".join(sorted(x for x in re.split(r"[+,&]", a) if x))
    if fmt == "order": return "←".join(x for x in re.split(r"[←,]", a) if x)
    return a.strip("'\"")


def check(c, out):
    """Returns a list of problems (empty = pass)."""
    f = fields(out); kind = f.get("KIND", "").lower(); typ = c.get("type", "rules"); bad = []
    if typ in QUESTION_TYPES:
        if kind != "question": return [f"kind={kind or '?'}"]
        got = f.get("ANSWER", "")
        if got != c["expected"]: bad.append(f"got {got!r} expected {c['expected']!r} conf={f.get('CONF', '')}")
    elif typ == "format":
        if kind != "question": return [f"kind={kind or '?'}"]
        if f.get("FORMAT", "choice") != c["format"]: bad.append(f"FORMAT={f.get('FORMAT', '-')} expected {c['format']}")
        if norm_fmt(c["format"], f.get("ANSWER", "")) != norm_fmt(c["format"], c["expected"]):
            bad.append(f"got {f.get('ANSWER', '')!r} expected {c['expected']!r}")
    elif typ == "instructions":
        if kind != "instructions": return [f"kind={kind or '?'}"]
        if c.get("passage") and f.get("PASSAGE", "no").lower() != c["passage"]: bad.append(f"PASSAGE={f.get('PASSAGE', '-')}")
    elif typ == "other":
        if kind != "other": return [f"kind={kind or '?'}"]
    elif typ == "self_report":
        if kind != "self_report": return [f"kind={kind or '?'}"]
        plain = f.get("PLAIN", ""); opts = [o.strip() for o in f.get("OPTIONS", "").split("|") if o.strip()]
        strip = lambda xs: [re.sub(r"^([א-ת]|[A-Ea-e]|\d)[.)]\s+", "", o) for o in xs]   # "א. אדווח" == "אדווח"
        if strip(opts) != strip(c["options"]): bad.append(f"options {opts} != {c['options']}")
        if not plain: bad.append("PLAIN missing")
        if "לא נכון לומר" in plain: bad.append(f"double negation kept: {plain}")
        if c.get("neg") and f.get("NEG", "").lower() != c["neg"]: bad.append(f"NEG={f.get('NEG', '-')} expected {c['neg']}")
        for w in c.get("require", []):
            if w not in plain: bad.append(f"qualifier {w!r} lost: {plain}")
        if f.get("ANSWER") or any(h in plain for h in NO_HINT): bad.append(f"suggested an answer: ANSWER={f.get('ANSWER', '')!r} PLAIN={plain}")
    return bad


def run(c):
    try:
        out, ms = ask(c["text"])
    except Exception as e:
        return c, f"ERROR {e}", ["request failed"], 0
    return c, out, check(c, out), ms


jobs_list = [c for c in cases for _ in range(reps)]
results = []
with ThreadPoolExecutor(max_workers=jobs) as ex:
    for c, out, bad, ms in ex.map(run, jobs_list):
        results.append((c, out, bad, ms))
        print(f"{c['id']:4} {'OK ' if not bad else 'BAD'} {ms:6} ms  {'; '.join(bad)}", flush=True)

by = {}
for c, out, bad, ms in results:
    t = by.setdefault(c.get("type", "rules"), [0, 0]); t[1] += 1; t[0] += not bad
print("\n== accuracy by type")
for t, (ok, tot) in sorted(by.items()):
    print(f"  {t:14} {ok}/{tot}")
ok = sum(1 for r in results if not r[2]); tot = len(results)
print(f"  {'TOTAL':14} {ok}/{tot}")
fails = [r for r in results if r[2]]
if fails:
    print("\n== failures (exact input + reply)")
    for c, out, bad, ms in fails:
        print(f"--- {c['id']} [{c.get('type', 'rules')}] {c.get('note', '')}\n{c['text']}\n>>> {'; '.join(bad)}\n" + "\n".join("    " + l for l in out.splitlines()))
if "--out" in opt:
    with open(opt["--out"], "a") as fh:
        for c, out, bad, ms in results:
            fh.write(json.dumps({"id": c["id"], "type": c.get("type", "rules"), "ok": not bad, "problems": bad, "ms": ms, "reply": out}, ensure_ascii=False) + "\n")
sys.exit(0 if ok == tot else 1)
