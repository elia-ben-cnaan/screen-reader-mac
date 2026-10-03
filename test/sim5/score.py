#!/usr/bin/env python3
"""Score `ScreenReader --run-sim` output against key.json. Files are named u<unit>_q<nn>.png (q00 = instructions)."""
import json, re, sys, os
key = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "key.json")))
ok = tot = lost = instr_ok = instr = 0; wrong = []
for line in open(sys.argv[1]):
    f = line.rstrip("\n").split("\t")
    if len(f) < 4 or not (m := re.match(r"u(\d)_q(\d+)\.png", f[0])): continue
    u, q = int(m[1]), int(m[2])
    if q == 0:
        instr += 1; instr_ok += f[1] == "instructions"; continue
    tot += 1; exp = key[u - 1]["answers"][q - 1]
    if f[1] != "question": lost += 1; wrong.append(f"u{u} q{q}: {f[1]}")
    elif f[2] == exp: ok += 1
    else: wrong.append(f"u{u} q{q}: got {f[2]} expected {exp} conf={f[3]}")
print(f"ACCURACY {ok}/{tot} ({100*ok//max(tot,1)}%) · not answered {lost} · instructions recognised {instr_ok}/{instr}")
for w in wrong: print("  " + w)
