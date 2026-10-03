#!/usr/bin/env python3
"""Score `ScreenReader --run-sim` output (TSV: file kind answer conf plain options neg ocr_ms server_ms format) against key.json.
Files: u<unit>_q<nn>.png, q00 = unit instructions. Units 1-5 objective (answer key), unit 6 = SELF_REPORT bank, unit 7 = formats."""
import json, re, sys, os, statistics
key = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "key.json")))
# must survive word for word (מעולם is exempt only inside a resolved double negation)
QUAL = ["לפעמים", "תמיד", "בדרך כלל", "מעולם", "אף פעם", "לעיתים", "רק"]
NO_HINT = ["מומלץ", "כדאי לבחור", "התשובה הנכונה", "עדיף לענות"]
words = lambda s: {w.strip("?,.") for w in s.split() if len(w.strip("?,.")) >= 4}
obj = dict(ok=0, tot=0, lost=0); instr = [0, 0]; fails = {}; sr = dict(ok=0, tot=0); lat = []
fm = dict(ok=0, tot=0)
def fnorm(fmt, a):
    a = re.sub(r"\s+", "", a).replace("<-", "←").replace("->", "→").strip(".")
    if fmt == "multi": return "+".join(sorted(x for x in re.split(r"[+,&]", a) if x))
    if fmt == "order": return "←".join(x for x in re.split(r"[←,]", a) if x)
    return a
def fail(group, msg): fails.setdefault(group, []).append(msg)
warns = {}
def warn(group, msg): warns.setdefault(group, []).append(msg)
for line in open(sys.argv[1]):
    f = line.rstrip("\n").split("\t") + [""] * 10
    m = re.match(r"u(\d)_q(\d+)\.png", f[0])
    if not m: continue
    u, q = int(m[1]), int(m[2])
    if f[7].isdigit() and f[8].isdigit(): lat.append(int(f[7]) + int(f[8]))
    if q == 0:
        instr[1] += 1; instr[0] += f[1] == "instructions"
        if f[1] != "instructions": fail("instructions", f"u{u}: {f[1]}")
        continue
    k = key[u - 1]
    if "formats" in k:                                  # unit 7: typed / order / multi
        fm["tot"] += 1; it = k["formats"][q - 1]
        if f[1] != "question": fail("formats: not answered / misrouted", f"u{u} q{q}: {f[1]}")
        elif fnorm(it["format"], f[2]) == fnorm(it["format"], it["answer"]) and (f[9] or "choice") == it["format"]: fm["ok"] += 1
        else: fail("formats: wrong answer/format", f"u{u} q{q}: got {f[2]!r} FORMAT={f[9] or '-'} expected {it['answer']!r} {it['format']}")
        continue
    if "answers" in k:                                  # objective routes: regression
        obj["tot"] += 1; exp = k["answers"][q - 1]
        if f[1] != "question": obj["lost"] += 1; fail("objective: not answered / misrouted", f"u{u} q{q}: {f[1]}")
        elif f[2] == exp: obj["ok"] += 1
        else: fail("objective: wrong answer", f"u{u} q{q}: got {f[2]} expected {exp} conf={f[3]}")
        continue
    it = k["items"][q - 1]; sr["tot"] += 1; tag = f"{it['id']} {it['family_id']} {it['challenge_tag']}"
    plain, opts, neg = f[4], [o.strip() for o in f[5].split("|") if o.strip()], f[6].lower()
    bad = []
    if f[1] != "self_report": bad.append(("classification", f"route={f[1]}"))
    else:
        if opts != it["options"]: bad.append(("option extraction", f"{opts} != {it['options']}"))
        if not plain: bad.append(("plain meaning missing", ""))
        if "לא נכון לומר" in plain or ("מעולם" in plain and "לא" in plain.split()): bad.append(("double negation not resolved", plain))
        if it["negation"] and neg != "yes": bad.append(("negation flag", f"NEG={neg}"))
        stmt = it["text"].replace("לא נכון לומר שמעולם לא היה מצב", "") if it["challenge_tag"] == "double_negation" else it["text"]
        lost_q = [w for w in QUAL if re.search(rf"(^|\s|ש|ו|כ|ב|ה){w}(\s|$|[?,.])", stmt) and w not in plain]
        if lost_q: bad.append(("qualifier lost", f"{lost_q} · {plain}"))
        if len(words(it["plain_meaning"]) & words(plain)) < max(1, len(words(it["plain_meaning"])) // 3):
            warn("wording differs from dataset plain meaning (word-overlap heuristic, review by eye)", f"{tag}: {plain} vs {it['plain_meaning']}")
        if f[2] or any(h in plain for h in NO_HINT): bad.append(("suggested an answer", f"ANSWER={f[2]}"))
    if bad:
        for g, msg in bad: fail(f"self_report: {g}", f"{tag}: {msg}")
    else: sr["ok"] += 1
print(f"OBJECTIVE (regression) {obj['ok']}/{obj['tot']} · not answered {obj['lost']}")
if fm["tot"]: print(f"FORMATS (typed/order/multi) {fm['ok']}/{fm['tot']}")
print(f"SELF_REPORT {sr['ok']}/{sr['tot']} passed all checks")
print(f"INSTRUCTIONS recognised {instr[0]}/{instr[1]}")
if lat: print(f"LATENCY ocr+server ms: avg {int(statistics.mean(lat))} · median {int(statistics.median(lat))} · worst {max(lat)} (n={len(lat)})")
for g, ms in sorted(fails.items(), key=lambda x: -len(x[1])):
    print(f"FAIL [{len(ms)}] {g}")
    for x in ms[:20]: print("    " + x)
for g, ms in warns.items():
    print(f"WARN [{len(ms)}] {g}")
    for x in ms[:20]: print("    " + x)
