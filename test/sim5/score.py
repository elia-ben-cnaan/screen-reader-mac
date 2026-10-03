#!/usr/bin/env python3
"""Score `ScreenReader --run-sim` output (TSV: file kind answer conf plain options neg ocr_ms server_ms) against key.json.
Files: u<unit>_q<nn>.png, q00 = unit instructions. Units 1-5 objective (answer key), unit 6 = SELF_REPORT bank."""
import json, re, sys, os, statistics
key = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "key.json")))
QUAL = ["מעולם", "אף פעם", "אי פעם", "תמיד", "בדרך כלל", "לעיתים", "לפעמים", "רק", "ללא", "בלי"]
NO_HINT = ["מומלץ", "כדאי לבחור", "התשובה הנכונה", "עדיף לענות"]
words = lambda s: {w.strip("?,.") for w in s.split() if len(w.strip("?,.")) >= 4}
obj = dict(ok=0, tot=0, lost=0); instr = [0, 0]; fails = {}; sr = dict(ok=0, tot=0); lat = []
def fail(group, msg): fails.setdefault(group, []).append(msg)
for line in open(sys.argv[1]):
    f = line.rstrip("\n").split("\t") + [""] * 9
    m = re.match(r"u(\d)_q(\d+)\.png", f[0])
    if not m: continue
    u, q = int(m[1]), int(m[2])
    if f[7].isdigit() and f[8].isdigit(): lat.append(int(f[7]) + int(f[8]))
    if q == 0:
        instr[1] += 1; instr[0] += f[1] == "instructions"
        if f[1] != "instructions": fail("instructions", f"u{u}: {f[1]}")
        continue
    k = key[u - 1]
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
        lost_q = [w for w in QUAL if w in it["text"] and w in it["plain_meaning"] and w not in plain]
        if lost_q: bad.append(("qualifier lost", f"{lost_q} · {plain}"))
        if len(words(it["plain_meaning"]) & words(plain)) < max(1, len(words(it["plain_meaning"])) // 3):
            bad.append(("meaning drift", f"{plain} vs {it['plain_meaning']}"))
        if f[2] or any(h in plain for h in NO_HINT): bad.append(("suggested an answer", f"ANSWER={f[2]}"))
    if bad:
        for g, msg in bad: fail(f"self_report: {g}", f"{tag}: {msg}")
    else: sr["ok"] += 1
print(f"OBJECTIVE (regression) {obj['ok']}/{obj['tot']} · not answered {obj['lost']}")
print(f"SELF_REPORT {sr['ok']}/{sr['tot']} passed all checks")
print(f"INSTRUCTIONS recognised {instr[0]}/{instr[1]}")
if lat: print(f"LATENCY ocr+server ms: avg {int(statistics.mean(lat))} · median {int(statistics.median(lat))} · worst {max(lat)} (n={len(lat)})")
for g, ms in sorted(fails.items(), key=lambda x: -len(x[1])):
    print(f"[{len(ms)}] {g}")
    for x in ms[:12]: print("    " + x)
