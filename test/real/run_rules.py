#!/usr/bin/env python3
"""Replay the 6 real-simulator rule questions (נכון / לא נכון / לא ניתן לדעת) against a proxy. Usage: run_rules.py [port] [repeats]"""
import json, os, sys, urllib.request
port = sys.argv[1] if len(sys.argv) > 1 else "8099"; reps = int(sys.argv[2]) if len(sys.argv) > 2 else 1
tok = open(os.path.expanduser("~/.config/screenreader/client_token")).read().strip()
cases = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules_tf.json")))
ok = tot = 0
for c in cases:
    for _ in range(reps):
        r = urllib.request.Request(f"http://127.0.0.1:{port}/ask", data=json.dumps({"text": c["text"]}).encode(), headers={"X-Token": tok})
        out = urllib.request.urlopen(r, timeout=120).read().decode()
        got = next((l.split(":", 1)[1].strip() for l in out.splitlines() if l.startswith("ANSWER:")), "?")
        tot += 1; ok += got == c["expected"]
        print(c["id"], "OK " if got == c["expected"] else "BAD", "got", got, "expected", c["expected"])
print(f"{ok}/{tot}")
