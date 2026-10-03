#!/usr/bin/env python3
"""SELF_REPORT QA bank, transcribed from SELF_REPORT_BANK pages received so far (pages 1-3 of 15 = SR-001..SR-060).
Per family the images show: topic, baseline statement, and the direct question (= plain meaning). The other 4 variants
on the pages follow fixed wording that was checked item by item against the images; they are written out in bank.json."""
import json, os
FAM = [  # family, topic, baseline statement (as on the page), direct question / plain meaning (as on the page)
("F-001","יושרה כללית","אני מקפיד על כללים גם כשאף אחד אינו בודק אותי","האם אתה מקפיד על כללים גם ללא פיקוח?"),
("F-002","יושרה כללית","קרה שהצגתי מצב בצורה מחמיאה יותר כדי להימנע מביקורת","האם הצגת מצב באופן מחמיא יותר כדי להימנע מביקורת?"),
("F-003","יושרה כללית","יש מצבים שבהם בעיניי מותר לעגל פינות אם התוצאה טובה","האם לדעתך לפעמים מותר לעגל פינות למען תוצאה טובה?"),
("F-004","יושרה כללית","כשאני מגלה שטעיתי אני מעדיף לתקן את הדבר גם אם איש לא הבחין","האם אתה מתקן טעות גם כשאיש לא הבחין בה?"),
("F-005","יושרה כללית","ההתנהגות שלי משתנה כשאני יודע שמפקחים עליי","האם פיקוח משנה את מידת ההקפדה שלך?"),
("F-006","מחויבות לארגון","עמדתי בהתחייבויות שקיבלתי גם כשהמשימה הייתה לא נוחה","האם אתה עומד בהתחייבויות גם כשלא נוח?"),
("F-007","מחויבות לארגון","עזבתי משימה באמצע בלי לעדכן את מי שהיה תלוי בה","האם עזבת משימה בלי לעדכן?"),
("F-008","מחויבות לארגון","אני משלים משימות חשובות גם כשאין מי שבודק אותי","האם אתה משלים משימות חשובות גם ללא פיקוח?"),
("F-009","מחויבות לארגון","הודעתי מראש כשידעתי שלא אצליח לעמוד בהתחייבות","האם אתה מודיע מראש כשלא תעמוד בהתחייבות?"),
("F-010","מחויבות לארגון","איחרתי בלי להודיע מראש למרות שיכולתי לעשות זאת","האם איחרת בלי להודיע למרות שיכולת?"),
("F-011","שמירה על רכוש","השתמשתי בציוד של מקום עבודה בלי לקבל רשות מראש","האם השתמשת בציוד של מקום עבודה ללא רשות?"),
("F-012","שמירה על רכוש","לקחתי הביתה פריט ששייך למקום העבודה בלי לוודא שמותר לי","האם לקחת הביתה רכוש של מקום העבודה ללא אישור?"),
]
OPT = {"agreement5": ["כלל לא מסכים","לא מסכים","ניטרלי","מסכים","מסכים מאוד"],
       "frequency5": ["אף פעם","לעיתים רחוקות","לפעמים","לעיתים קרובות","תמיד"],
       "yes_no": ["כן","לא"], "true_false": ["נכון לגביי","לא נכון לגביי"]}
items = []
for fi, (fam, topic, base, q) in enumerate(FAM):
    core = q[len("האם "):].rstrip("?")
    variants = [
        ("baseline", base, "agreement5", "היגד ישיר", 0),
        ("frequency", f"באיזו תדירות נכון לומר ש{base}?", "frequency5", "תדירות", 0),
        ("question", q, "yes_no", "שאלה ישירה", 0),
        ("double_negation", f"לא נכון לומר שמעולם לא היה מצב שבו {core}", "agreement5", "שלילה כפולה", 2),
        ("contextual", f"גם במצב לא נוח, {base}", "true_false", "הקשר נוסף", 0)]
    for vi, (tag, text, fmt, stype, neg) in enumerate(variants):
        items.append({"id": f"SR-{fi*5+vi+1:03d}", "family_id": fam, "topic": topic, "challenge_tag": tag,
                      "text": text, "options": OPT[fmt], "format": fmt, "statement_type": stype,
                      "negation": neg, "plain_meaning": q})
# dataset validation (spec §13) against what was actually received
ids = [i["id"] for i in items]
fams = {}
for i in items: fams[i["family_id"]] = fams.get(i["family_id"], 0) + 1
print(f"pages received: 3/15 · items: {len(items)} (expected 300) · unique ids: {len(set(ids))} · families: {len(fams)} (expected 60) · "
      f"all families x5: {all(v == 5 for v in fams.values())} · missing text/options: {sum(1 for i in items if not i['text'] or not i['options'])}")
json.dump(items, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bank.json"), "w"), ensure_ascii=False, indent=1)
