#!/usr/bin/env python3
"""Builds the 5-unit x 50-question test simulator. Answers go to key.json (server only, never in the page).
Units: analogies (hand-written), word problems, number sequences, shape matrices, bar charts — all with one correct option."""
import json, random, os
R = random.Random(7)
PER_UNIT = int(os.environ.get("PER_UNIT", "5"))   # bank has 50 per unit
HE = "אבגד"
OUT = os.path.dirname(os.path.abspath(__file__))

def mc(correct, distractors):
    """Shuffle 4 options; return (options, correct_index)."""
    opts = [correct] + list(distractors)[:3]
    assert len(set(map(str, opts))) == 4, opts
    R.shuffle(opts)
    return opts, opts.index(correct)

# ---------- Unit 1: analogies (pair, correct, 3 distractors)
AN = [
("ציפור : להקה","עץ : יער",["דג : מים","ספר : דף","כלב : חתול"]),
("רופא : בית חולים","מורה : בית ספר",["עט : נייר","שופט : עורך דין","טבח : סיר"]),
("חם : רותח","קר : קפוא",["גבוה : נמוך","שמח : עצוב","אור : חושך"]),
("מספריים : לגזור","עט : לכתוב",["שולחן : עץ","ספר : ספרייה","כיסא : רגל"]),
("גור : כלב","גוזל : ציפור",["חתול : עכבר","פרה : חלב","דבורה : כוורת"]),
("אצבע : יד","בוהן : רגל",["עין : משקפיים","כובע : ראש","לב : דם"]),
("צמא : מים","רעב : אוכל",["קור : שלג","שמש : חום","ספר : קריאה"]),
("לבנה : קיר","אבן : חומה",["גל : חוף","ענן : גשם","מים : קרח"]),
("כנר : כינור","צייר : מכחול",["חייט : בגד","זמר : שיר","נגר : עץ"]),
("שקר : אמת","מלחמה : שלום",["עיר : רחוב","חבר : ידיד","מים : נהר"]),
("גדול : ענק","קטן : זעיר",["ישן : חדש","מהיר : איטי","כבד : משקל"]),
("מנעול : מפתח","בעיה : פתרון",["דלת : חלון","בית : חדר","שעון : זמן"]),
("חיטה : לחם","ענבים : יין",["תפוח : עץ","חלב : פרה","מלח : ים"]),
("שעון : זמן","מדחום : טמפרטורה",["מפה : דרך","מזלג : אוכל","מטרייה : גשם"]),
("נמלה : חרק","לוויתן : יונק",["נחש : ארס","צב : שריון","כריש : ים"]),
("עיוור : ראייה","חירש : שמיעה",["צולע : מקל","אילם : מילה","רעב : לחם"]),
("קשת : חץ","רובה : כדור",["חרב : מגן","כדור : רגל","מטוס : שמיים"]),
("פסל : שיש","סוודר : צמר",["עוגה : תנור","ספר : סופר","בית : רחוב"]),
("ראש : כובע","רגל : נעל",["יד : אצבע","עין : דמעה","צוואר : ראש"]),
("צלצול : פעמון","נביחה : כלב",["רעם : ברק","שיר : מילים","רוח : עץ"]),
("תלמיד : כיתה","חייל : פלוגה",["מורה : שיעור","מלך : כתר","שחקן : במה"]),
("אביב : עונה","יולי : חודש",["שבוע : יום","בוקר : ערב","שנה : מאה"]),
("זהב : מתכת","ורד : פרח",["עלה : גבעול","אבן : קיר","עץ : שורש"]),
("דייג : חכה","צלם : מצלמה",["דג : רשת","שחיין : מים","טבח : מסעדה"]),
("רעב : לאכול","עייף : לישון",["שמח : לבכות","חולה : לרוץ","קר : קרח"]),
("שמש : יום","ירח : לילה",["כוכב : שמיים","ענן : גשם","חושך : אור"]),
("קמח : עוגה","עץ : רהיט",["ביצה : תרנגולת","מים : צמא","תנור : אפייה"]),
("מילה : משפט","תו : מנגינה",["דף : עט","קול : אוזן","שיר : משורר"]),
("מהיר : צבי","איטי : צב",["חזק : חלש","גבוה : הר","לבן : שחור"]),
("חלון : זכוכית","צמיג : גומי",["דלת : בית","מכונית : כביש","ספר : מדף"]),
("מרפק : זרוע","ברך : רגל",["כתף : צוואר","אצבע : ציפורן","גב : בטן"]),
("מים : לרתוח","קרח : להימס",["אש : לכבות","אוויר : לנשום","שלג : לרדת"]),
("עכביש : קורים","דבורה : כוורת",["ציפור : כנף","נמלה : חרק","פרפר : פרח"]),
("אורח : מארח","לקוח : מוכר",["חבר : חברה","ילד : ילדה","שכן : רחוב"]),
("שחמט : משחק","פטיש : כלי",["לוח : גיר","כדור : רגל","ספר : קריאה"]),
("קיץ : חום","חורף : קור",["אביב : סתיו","גשם : מטרייה","שלג : לבן"]),
("מדחום : חום","סרגל : אורך",["מספריים : נייר","מחשב : מקלדת","עיפרון : מחק"]),
("מלך : ממלכה","נשיא : מדינה",["שר : ממשלה","חייל : צבא","תלמיד : מורה"]),
("גשם : שיטפון","רוח : סופה",["שמש : צל","שלג : קור","ענן : שמיים"]),
("לחישה : צעקה","טפטוף : מבול",["שיר : מנגינה","בכי : דמעה","קול : אוזן"]),
("בצל : דמעות","בדיחה : צחוק",["עגבנייה : סלט","תפוח : עץ","מלח : ים"]),
("צבעים : צייר","מילים : משורר",["פסנתר : קלידים","ספר : ספרייה","מברשת : שיער"]),
("טלפון : שיחה","עט : כתיבה",["מנורה : חשמל","מחשב : שולחן","תיק : בית ספר"]),
("אי : ים","נווה מדבר : מדבר",["הר : עמק","נהר : גשר","חוף : חול"]),
("שופט : פסק דין","רופא : אבחנה",["עורך דין : לקוח","מורה : תלמיד","חוק : משטרה"]),
("ענף : עץ","נוצה : ציפור",["שורש : אדמה","עלה : ירוק","פרי : מיץ"]),
("סופר : ספר","אדריכל : בניין",["קורא : עיתון","מורה : כיתה","צייר : מכחול"]),
("ישן : ער","סגור : פתוח",["עייף : ישנוני","חם : לוהט","גדול : רחב"]),
("פרח : ניצן","פרפר : זחל",["עץ : יער","גשם : ענן","דבורה : דבש"]),
("מלח : מלוח","סוכר : מתוק",["לימון : צהוב","פלפל : ירוק","מים : צלול"]),
]
def unit_analogies():
    qs = []
    for pair, c, d in AN:
        o, k = mc(c, d)
        qs.append({"stem": f"<b class=big>{pair}</b>", "opts": o, "ans": k})
    return qs

# ---------- Unit 2: word problems (computed)
def unit_quant():
    qs = []
    def num_opts(c, unit=""):
        ds = set()
        while len(ds) < 3:
            v = c + R.choice([-3, -2, -1, 1, 2, 3, 4, 5]) * max(1, c // 10 if c >= 10 else 1)
            if v > 0 and v != c: ds.add(v)
        o, k = mc(f"{c}{unit}", [f"{v}{unit}" for v in ds])
        return o, k
    gens = []
    def speed():
        v = R.choice([40, 50, 60, 70, 80, 90]); t = R.choice([2, 3, 4, 5]); t2 = R.choice([2, 3, 4, 5, 6])
        return f"מכונית נסעה {v*t} ק״מ ב־{t} שעות במהירות קבועה. כמה ק״מ תעבור ב־{t2} שעות?", v * t2, " ק״מ"
    def work():
        a = R.choice([2, 3, 4, 6]); d = R.choice([6, 8, 12, 24]); b = R.choice([x for x in [2, 3, 4, 6, 8, 12] if (a * d) % x == 0 and x != a])
        return f"{a} פועלים מסיימים עבודה ב־{d} ימים. בכמה ימים יסיימו אותה {b} פועלים באותו קצב?", a * d // b, " ימים"
    def percent():
        p = R.choice([10, 20, 25, 30, 40, 50]); x = R.choice([80, 120, 200, 240, 300, 400, 500])
        return f"מחיר מוצר הוא {x} ש״ח. המחיר הוזל ב־{p}%. מה המחיר החדש?", x * (100 - p) // 100, " ש״ח"
    def ages():
        s = R.choice([4, 5, 6, 7, 8, 9, 10]); m = R.choice([3, 4]); y = R.choice([2, 3, 4, 5])
        return f"גיל האב גדול פי {m} מגיל בנו. גיל הבן {s}. בן כמה יהיה האב בעוד {y} שנים?", s * m + y, ""
    def ratio():
        a, b = R.choice([(2, 3), (3, 5), (1, 4), (3, 4), (2, 5)]); t = (a + b) * R.choice([4, 5, 6, 8, 10])
        return f"בכיתה {t} תלמידים. היחס בין בנים לבנות הוא {a}:{b}. כמה בנות בכיתה?", t * b // (a + b), ""
    def price():
        n = R.choice([3, 4, 5, 6]); p = R.choice([12, 15, 18, 25]); m = R.choice([7, 8, 9, 10])
        return f"{n} מחברות עולות {n*p} ש״ח. כמה יעלו {m} מחברות?", m * p, " ש״ח"
    def avg():
        xs = [R.choice(range(60, 100, 2)) for _ in range(3)]; tot = R.choice(range(70, 95)) * 4; last = tot - sum(xs)
        if not 40 <= last <= 100: return avg()
        return f"ממוצע 4 מבחנים הוא {tot//4}. ציוני שלושת הראשונים: {xs[0]}, {xs[1]}, {xs[2]}. מה הציון הרביעי?", last, ""
    def pool():
        a = R.choice([2, 3, 4, 6]); b = R.choice([x for x in [3, 4, 6, 12] if x != a])
        from fractions import Fraction as F
        t = 1 / (F(1, a) + F(1, b))
        if t.denominator not in (1, 2, 4, 5): return pool()
        v = float(t)
        c = (str(int(v)) if v == int(v) else f"{v:g}")
        ds = {f"{v + d:g}" for d in (-1, 0.5, 1, 1.5, -0.5) if v + d > 0} - {c}
        o, k = mc(c + " שעות", [x + " שעות" for x in list(ds)[:3]])
        return ("POOL", f"ברז א׳ ממלא בריכה ב־{a} שעות וברז ב׳ ב־{b} שעות. בכמה שעות ימלאו אותה יחד?", o, k)
    gens = [speed, work, percent, ages, ratio, price, avg, pool]
    seen = set()
    while len(qs) < 50:
        g = R.choice(gens)()
        if g[0] == "POOL":
            _, stem, o, k = g
        else:
            stem, c, u = g; o, k = num_opts(c, u)
        if stem in seen: continue
        seen.add(stem); qs.append({"stem": stem, "opts": o, "ans": k})
    return qs

# ---------- Unit 3: number sequences
def unit_seq():
    qs = []; seen = set()
    def ar():
        a = R.randint(1, 30); d = R.choice([3, 4, 5, 6, 7, 9, 11, -4, -6]); return [a + i * d for i in range(6)]
    def geo():
        a = R.choice([1, 2, 3, 5]); r = R.choice([2, 3]); return [a * r ** i for i in range(6)]
    def second():
        a = R.randint(1, 10); d = R.randint(1, 4); s = R.choice([1, 2, 3]); out = [a]
        for i in range(5): out.append(out[-1] + d + s * i)
        return out
    def alt():
        a, b = R.randint(1, 20), R.randint(30, 60); p, q = R.choice([2, 3, 5]), R.choice([-1, -2, -3])
        return [a + (i // 2) * p if i % 2 == 0 else b + (i // 2) * q for i in range(6)]
    def sq():
        o = R.randint(1, 5); return [(o + i) ** 2 for i in range(6)]
    def fib():
        a, b = R.randint(1, 5), R.randint(2, 7); out = [a, b]
        while len(out) < 6: out.append(out[-1] + out[-2])
        return out
    def mul_add():
        a = R.randint(1, 4); m = 2; c = R.choice([1, 2, 3]); out = [a]
        for _ in range(5): out.append(out[-1] * m + c)
        return out
    gens = [ar, geo, second, alt, sq, fib, mul_add]
    while len(qs) < 50:
        s = R.choice(gens)(); key = tuple(s)
        if key in seen: continue
        seen.add(key); c = s[-1]
        ds = {c + d for d in R.sample([-3, -2, -1, 1, 2, 4, 6, 10], 6)} - {c}
        o, k = mc(str(c), [str(x) for x in list(ds)[:3]])
        qs.append({"stem": "השלם את הסדרה:<br><b class=big dir=ltr>" + ", ".join(map(str, s[:-1])) + ", ?</b>", "opts": o, "ans": k})
    return qs

# ---------- Unit 4: shape matrices (SVG)
SH = ["circle", "square", "triangle", "diamond"]
def shape(k, cx, cy, r, fill="none"):
    st = f'fill="{fill}" stroke="#111" stroke-width="2.5"'
    return {"circle": f'<circle cx="{cx}" cy="{cy}" r="{r}" {st}/>',
            "square": f'<rect x="{cx-r}" y="{cy-r}" width="{2*r}" height="{2*r}" {st}/>',
            "triangle": f'<polygon points="{cx},{cy-r} {cx+r},{cy+r} {cx-r},{cy+r}" {st}/>',
            "diamond": f'<polygon points="{cx},{cy-r} {cx+r},{cy} {cx},{cy+r} {cx-r},{cy}" {st}/>'}[k]
FILLS = ["none", "#999", "#111"]
def cell(sh, n=1, fill="none", rot=0):
    if n == 1: body = shape(sh, 40, 40, 20, fill)
    else:
        pos = {2: [(25, 40), (55, 40)], 3: [(20, 40), (40, 40), (60, 40)]}[n]
        body = "".join(shape(sh, x, y, 9, fill) for x, y in pos)
    if rot: body = f'<g transform="rotate({rot} 40 40)">{body}</g>'
    return body
def svg(body, w=80, h=80): return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">{body}</svg>'
def arrow(rot): return f'<g transform="rotate({rot} 40 40)"><line x1="40" y1="62" x2="40" y2="20" stroke="#111" stroke-width="3"/><polygon points="40,12 31,26 49,26" fill="#111"/></g>'
def grid(cells):
    g = ""
    for i, c in enumerate(cells):
        x, y = (i % 3) * 90, (i // 3) * 90
        g += f'<rect x="{x+2}" y="{y+2}" width="86" height="86" fill="#fff" stroke="#888"/>'
        g += f'<g transform="translate({x+5},{y+5})">' + (c if c is not None else '<text x="40" y="52" font-size="36" text-anchor="middle" fill="#888">?</text>') + "</g>"
    return svg(g, 274, 274)
def unit_matrix():
    qs = []; seen = set()
    while len(qs) < 50:
        kind = R.choice(["count", "latin", "fill", "rot"])
        if kind == "count":
            rows = R.sample(SH, 3); f = R.choice(FILLS[:2])
            cells = [cell(rows[r], c + 1, f) for r in range(3) for c in range(3)]
            ans = cells[8]; ds = [cell(rows[2], 2, f), cell(rows[1], 3, f), cell(rows[2], 3, "#111" if f == "none" else "none")]
            sig = ("count", tuple(rows), f)
        elif kind == "latin":
            s = R.sample(SH, 3); perm = [s, s[1:] + s[:1], s[2:] + s[:2]]; f = R.choice(FILLS)
            cells = [cell(perm[r][c], 1, f) for r in range(3) for c in range(3)]
            ans = cells[8]; other = [x for x in SH if x != perm[2][2]]
            ds = [cell(other[0], 1, f), cell(other[1], 1, f), cell(perm[2][2], 2, f)]
            sig = ("latin", tuple(s), f)
        elif kind == "fill":
            rows = R.sample(SH, 3); order = R.sample(FILLS, 3)
            cells = [cell(rows[r], 1, order[c]) for r in range(3) for c in range(3)]
            ans = cells[8]; ds = [cell(rows[2], 1, order[0]), cell(rows[2], 1, order[1]), cell(rows[1], 1, order[2])]
            sig = ("fill", tuple(rows), tuple(order))
        else:
            step = R.choice([45, 90]); base = [R.choice([0, 45, 90, 135, 180]) for _ in range(3)]
            cells = [arrow(base[r] + c * step) for r in range(3) for c in range(3)]
            a = base[2] + 2 * step; ans = cells[8]
            ds = [arrow(a + 90), arrow(a + 180), arrow(a - step)] if step == 45 else [arrow(a + 45), arrow(a + 180), arrow(a - step)]
            sig = ("rot", step, tuple(base))
        if sig in seen: continue
        seen.add(sig)
        cells[8] = None
        o, k = mc(svg(ans), [svg(d) for d in ds])
        qs.append({"stem": "איזו צורה משלימה את המטריצה?" + grid(cells), "opts": o, "ans": k, "svgopts": True})
    return qs

# ---------- Unit 5: bar charts
MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני"]
def chart(labels, vals, title):
    W, H, top = 520, 260, 20; mx = max(vals); bw = 56; gap = (W - 60 - bw * len(vals)) / len(vals)
    g = f'<line x1="50" y1="{H-30}" x2="{W-10}" y2="{H-30}" stroke="#333"/><line x1="50" y1="{top}" x2="50" y2="{H-30}" stroke="#333"/>'
    for t in range(0, mx + 1, 20 if mx > 100 else 10):
        y = H - 30 - (H - 30 - top) * t / (mx * 1.1)
        g += f'<text x="44" y="{y+4:.0f}" font-size="12" text-anchor="end">{t}</text><line x1="50" y1="{y:.0f}" x2="{W-10}" y2="{y:.0f}" stroke="#ddd"/>'
    for i, (l, v) in enumerate(zip(labels, vals)):
        x = 60 + i * (bw + gap); h = (H - 30 - top) * v / (mx * 1.1)
        g += f'<rect x="{x:.0f}" y="{H-30-h:.0f}" width="{bw}" height="{h:.0f}" fill="#4a78b8"/>'
        g += f'<text x="{x+bw/2:.0f}" y="{H-30-h-6:.0f}" font-size="13" text-anchor="middle">{v}</text>'
        g += f'<text x="{x+bw/2:.0f}" y="{H-12}" font-size="13" text-anchor="middle">{l}</text>'
    return f'<div class=cap>{title}</div>' + svg(g, W, H)
def unit_charts():
    qs = []; seen = set()
    titles = ["מספר המבקרים במוזיאון (באלפים)", "מכירות החנות (באלפי ש״ח)", "כמות הגשם (מ״מ)", "מספר הנרשמים לקורס"]
    while len(qs) < 50:
        n = R.choice([4, 5, 6]); labels = MONTHS[:n]
        vals = [R.choice(range(20, 160, 5)) for _ in range(n)]
        if len(set(vals)) < n: continue
        i, j = R.sample(range(n), 2); kind = R.choice(["diff", "max", "sum", "ratio", "pct", "avg"])
        if kind == "diff": q = f"בכמה גדול הערך ב{labels[max(i,j,key=lambda t: vals[t])]} מהערך ב{labels[min(i,j,key=lambda t: vals[t])]}?"; c = abs(vals[i] - vals[j])
        elif kind == "max": q = "באיזה חודש התקבל הערך הגבוה ביותר?"; c = labels[vals.index(max(vals))]
        elif kind == "sum": q = f"מה סכום הערכים ב{labels[i]} וב{labels[j]}?"; c = vals[i] + vals[j]
        elif kind == "ratio":
            a, b = vals[i], vals[j]
            if a % b: continue
            q = f"פי כמה גדול הערך ב{labels[i]} מהערך ב{labels[j]}?"; c = a // b
            if c < 2: continue
        elif kind == "pct":
            a, b = vals[i], vals[j]
            if b <= a or ((b - a) * 100) % a: continue
            q = f"בכמה אחוזים גדל הערך מ{labels[i]} ל{labels[j]}?"; c = (b - a) * 100 // a
            o, k = mc(f"{c}%", [f"{c+d}%" for d in R.sample([-20, -10, -5, 5, 10, 20], 3) if c + d > 0][:3] or [f"{c+7}%", f"{c+15}%", f"{c+25}%"])
            key = (tuple(vals), q)
            if key in seen or len(o) < 4: continue
            seen.add(key); qs.append({"stem": q + chart(labels, vals, R.choice(titles)), "opts": o, "ans": k}); continue
        else:
            if sum(vals) % n: continue
            q = "מה הממוצע של כל הערכים?"; c = sum(vals) // n
        key = (tuple(vals), q)
        if key in seen: continue
        seen.add(key)
        if kind == "max":
            o, k = mc(c, [l for l in labels if l != c][:3] if n > 3 else None)
        else:
            ds = {c + d for d in R.sample([-15, -10, -5, 5, 10, 15, 20], 5) if c + d > 0} - {c}
            if kind == "ratio": ds = {c + 1, c + 2, max(1, c - 1) if c > 2 else c + 3} - {c}
            o, k = mc(str(c), [str(x) for x in list(ds)[:3]])
        qs.append({"stem": q + chart(labels, vals, R.choice(titles)), "opts": o, "ans": k})
    return qs

UNITS = [
 ("אנלוגיות", "בכל שאלה מוצג זוג מילים שיש ביניהן קשר מסוים. מצאו בין התשובות את הזוג שהקשר בין מילותיו דומה ביותר לקשר שבזוג הנתון. שימו לב לכיוון הקשר.", unit_analogies),
 ("בעיות כמותיות", "בכל שאלה מוצגת בעיה מילולית. פתרו את הבעיה ובחרו את התשובה הנכונה. אין צורך במחשבון.", unit_quant),
 ("סדרות מספרים", "בכל שאלה מוצגת סדרת מספרים הבנויה לפי חוק מסוים. מצאו את החוק ובחרו את המספר שמשלים את הסדרה.", unit_seq),
 ("מטריצות צורות", "בכל שאלה מוצגת מטריצה של 3 על 3 משבצות שבה משבצת אחת חסרה. השורות והעמודות בנויות לפי חוקיות. בחרו את הצורה שמשלימה את המטריצה.", unit_matrix),
 ("גרפים", "בכל שאלה מוצג גרף עמודות. קראו את הנתונים מהגרף וענו על השאלה.", unit_charts),
]
data, key = [], []
for ui, (name, instr, gen) in enumerate(UNITS):
    qs = gen(); assert len(qs) == 50, (name, len(qs))
    qs = qs[:PER_UNIT]
    data.append({"name": name, "instr": instr, "qs": [{k: v for k, v in q.items() if k != "ans"} for q in qs]})
    key.append({"unit": ui + 1, "name": name, "answers": [HE[q["ans"]] for q in qs]})
# SELF_REPORT section: every item of test/self_report/bank.json, options as defined per item (no correct answer)
SR = json.load(open(os.path.join(OUT, "..", "self_report", "bank.json")))
if os.environ.get("SR_SHUFFLE"): R.shuffle(SR)
data.append({"name": "שאלון אישי", "sr": True,
             "instr": "בחלק זה יוצגו היגדים ושאלות על התנהגותך ועמדותיך. אין תשובות נכונות או שגויות. בחרו את התשובה המתארת אתכם בצורה הטובה ביותר.",
             "qs": [{"stem": f"<b class=big>{i['text']}</b>", "opts": i["options"], "id": i["id"]} for i in SR]})
key.append({"unit": len(data), "name": "SELF_REPORT", "items": SR})
json.dump(key, open(os.path.join(OUT, "key.json"), "w"), ensure_ascii=False, indent=0)
html = open(os.path.join(OUT, "template.html")).read().replace("/*DATA*/", json.dumps(data, ensure_ascii=False))
open(os.path.join(OUT, "index.html"), "w").write(html)
print("built", sum(len(u["qs"]) for u in data), "questions")
