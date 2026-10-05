#!/usr/bin/env python3
"""ScreenReader proxy: Mac app -> this server -> cheap model (Gemini Flash). Key stays here.

POST /ask  header X-Token: <client token>
  body {"text": "<OCR>", "image": "<base64 png>|null", "context": "<unit instructions / passage so far>"}
Response: text/plain lines (format in PROMPT). If the fast model is unsure, a stronger model re-checks;
"CHECKING" is sent first so the app can show it.
Config (/root/.config/screenreader/): llm_key (Gemini API key), client_token (shared with the app).
"""
import hashlib, json, os, re, threading, time, urllib.request, urllib.error
MAX_BODY = 15 * 1024 * 1024       # a screenshot is ~1-3 MB; anything bigger is rejected before reading
RATE_PER_MIN = 40                 # per address
hits, cache = {}, {}              # address -> recent request times; screen hash -> reply (last 500)
blocked = {}   # model -> unix time its quota frees up (from Google's "retry in ...")
# Spend guard: every model call is counted per day; past DAILY_MAX the server answers "limit" instead of calling
# the paid model (a leaked token or a runaway test cannot drain the prepaid credit). 0 = no cap.
DAILY_MAX = int(os.environ.get("SR_DAILY_MAX", "1500"))
calls = {"day": "", "n": 0}
calls_lock = threading.Lock()
def count_call(model):
    """Returns False when today's budget is used up. Logs one line per call (no question text)."""
    with calls_lock:
        day = time.strftime("%Y-%m-%d")
        if calls["day"] != day: calls["day"], calls["n"] = day, 0
        if DAILY_MAX and calls["n"] >= DAILY_MAX: return False
        calls["n"] += 1; n = calls["n"]
    print(f"call {n}/{DAILY_MAX or '-'} {model}", flush=True)
    return True
# Non-retryable failures get a reply the app can show as is (Hebrew first line) and must not retry.
def error_reply(code, msg): return f"{msg}\nKIND: error\nCODE: {code}"
CREDIT_MSG = "נגמר הקרדיט בשרת — צריך להטעין כדי להמשיך"
LIMIT_MSG = "הגענו לתקרת השאלות היומית בשרת"
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONF = os.path.expanduser("~/.config/screenreader")
PORT = int(os.environ.get("SR_PORT", "8099"))
# Paid tier (Tier 1). Order = preference; a model is skipped while Google reports it over quota.
FAST = os.environ.get("SR_MODELS", "gemini-flash-latest,gemini-3.8-flash,gemini-flash-lite-latest").split(",")
STRONG = os.environ.get("SR_STRONG", "gemini-pro-latest,gemini-3.8-flash").split(",")
# Accuracy over speed (owner's call, 2026-10-05): every screen goes to the strongest model with full thinking;
# the fast models are only a fallback when it is unavailable.
PRIMARY = os.environ.get("SR_PRIMARY", "gemini-pro-latest").split(",") + FAST

GUIDE = """How to solve each kind (use the unit instructions in CONTEXT when present — they define the rules):
- Analogies: find the exact relation in the given pair (part-whole, cause, degree, tool-use...), pick the option with the same relation in the same direction.
- Sentence completion: choose the words that keep the sentence's logic (contrast words like אבל/למרות flip the meaning).
- Reading comprehension: answer only from the passage in CONTEXT/screen, not world knowledge.
- Word problems / quantitative: set up the equation, compute exactly, match units and the option.
- Number/letter sequences: test differences, second differences, ratios, alternating sequences, positions.
- Matrices (3x3 shapes): find the rule per row AND per column (shape, count, rotation, fill, add/subtract); the missing cell must satisfy both.
- Odd one out / shapes: find the property all share except one (sides, symmetry, rotation, count, fill).
- Graphs and tables: read exact values from the image, compute what is asked (difference, ratio, percent change).
- Logic / syllogisms: test each option against every condition; eliminate. "All A are B" does not mean all B are A.
- Synonyms / antonyms / odd word out: find the precise shared meaning or category; prefer the closest, not a loose association.
- Idioms and proverbs: pick the meaning, not the literal reading.
- Quantitative comparison (A vs B): if the relation can change with allowed values, the answer is "cannot be determined".
- Data sufficiency: decide whether each statement alone / together is enough; do not actually need the value.
- Geometry: use the given numbers only, not how the drawing looks; recall area, angle sum, Pythagoras.
- Clocks / calendars: count carefully (minute hand 6°/min, hour hand 0.5°/min; weekdays mod 7).
- Codes (letters <-> numbers, substitutions): decode the given example letter by letter, then apply.
- Cube nets / folding, rotation vs mirror, hidden figure, dominoes: reason from the image; a mirror image is never a rotation.
- Attention / accuracy (compare strings, count symbols): compare character by character from the image, not the OCR.
- English: vocabulary, restatement (same meaning, not just same words), reading comprehension from the text only.
- True / False / Cannot tell (נכון / לא נכון / לא ניתן לדעת) on a short set of rules + facts:
  first separate the CLAIM (the sentence in quotes / after "הטענה") from the FACTS: the claim is what you test, never
  use it as a fact. Then treat the given rules as the COMPLETE procedure ("על סמך הכתוב/הנוהל בלבד"): the listed rules are the only source of any obligation,
  so if no rule is triggered by the facts, the obligation did not exist (that is לא נכון, not לא ניתן לדעת). Method: (1) write each rule as "IF condition THEN result";
  (2) compute every condition from the facts exactly (compare amounts to thresholds — "עולה על X" is strictly more
  than X, subtract minutes from departure times, count days from the given dates); a rule for a special case
  (urgent/critical, new account, club member) overrides the general rule whenever that case applies; (3) decide:
  נכון = the claim follows necessarily. לא נכון = the rules+facts contradict the claim — including "X was required"
  when no rule that requires X applies (every triggering condition is false), and a general claim that a listed
  exception or a fact violates. לא ניתן לדעת = only when the claim depends on something the text never states.
  Traps: "only if A" does not mean A alone is enough; a rule "no B -> returned" does not mean every return is because
  of no B (other rules may cause it), and a rejection never tells you which other documents were included.
  Direction: a rule "A -> B" plus the fact B does NOT give A. When the facts state only an outcome (he got a warning
  letter, it was rejected) and the claim is about its cause, and two or more rules lead to that outcome, the answer is
  לא ניתן לדעת. "A -> B" plus "not B" does give "not A" (נכון).
  Do not answer לא ניתן לדעת just because a value must be calculated — calculate it. When the claim states a number
  (a fine, a sum, a time), compute the number from the rules and compare: equal -> נכון, different -> לא נכון; the
  ANSWER must match the result of your own calculation in WHY.
- Situational judgment (work scenarios, "מה נכון לעשות"): the best option keeps responsibility toward whoever gave the
  task or instruction, serves the goal, and is transparent — e.g. finish or pause and bring the improvement to the
  manager with a comparison. Weaker options: acting alone against the instruction, hiding or ignoring the issue,
  doing nothing, delaying everything, or an extreme / escalating reaction. Prefer the balanced, proactive option.
- Symbol / operation puzzles (a legend of symbols -> operations, then a chain of symbols): read the legend first, map each
  symbol in the chain carefully from the IMAGE (□ empty vs ▣ filled vs ■ black are different), apply the operations one by
  one in order and write every intermediate result in WORK (e.g. QLCW -> QQLCW -> QQLWC); the option equal to the last
  result is the answer.
- Mental rotation vs mirror (flags, arrows, L-shapes, asymmetric figures): pick two distinct features (e.g. the flag and
  the dot, or the short and the long arm) and note their order going clockwise. A rotation keeps that order; a mirror image
  reverses it. Check every option this way; an option identical in orientation to the base shape counts as a rotation of
  0° unless the question asks for a different one. Never choose a mirror image for "סיבוב".
- Cube nets: in a net, two faces with exactly one face between them in a straight line are OPPOSITE and can never be seen
  together on a folded cube. For each option, list the visible faces, reject any option showing an opposite pair, then
  check adjacency/orientation of the remaining ones. Write the opposite pairs in WORK first.
- Answer options in a grid (several rows, some without letters): count every option box in reading order (right-to-left,
  top row first, then the next row) and use its own label if printed, otherwise the next letter in sequence.
- Multi-step list questions ("קודם סננו ואז ספרו", "מבין המספרים הגדולים מ-X, מהו השני"): use the printed item numbers
  for order (OCR of right-to-left lines can scramble it), filter first (strictly greater = excludes X itself), then count.
  Write the filtered list in WORK.
- Numbers on screen: Hebrew right-to-left text can scramble the order of numbers in OCR; trust the image for order."""

PROMPT = """You assist with a multiple-choice practice simulator (Hebrew or English). Input: noisy OCR of the captured screen, sometimes an image of it, and CONTEXT = instructions of the current unit (and a reading passage) seen earlier.
First classify the screen:
- INSTRUCTIONS: a unit/section intro explaining the question type or rules (no answer options to choose). A screen with a
  question and answer options — even if the options are only drawings with letters (א ב ג ד) and there is little text —
  is a QUESTION, never INSTRUCTIONS.
- QUESTION: one active question with answer options.
- SELF_REPORT: a statement or question about the test-taker's OWN behavior, habits, attitudes or opinions, answered on a
  personal scale (yes/no, true/not true for me, agreement, frequency), and questions about the test-taker's own past
  (כמה פעמים איחרת...). It has no objectively correct answer — never give ANSWER for it.
- Situational judgment (a work scenario + "מה נכון לעשות / מה הדרך הטובה ביותר / מה עליך לעשות / מה תעשה / כיצד תנהג",
  with options that are different actions) is a QUESTION: pick the best action and explain why in WHY.
  A question about facts, numbers, a text or given rules is a QUESTION even if worded in first person or answered כן/לא.
- OTHER: anything else (menu, loading, score, unrelated app).
Reply with these lines only, no extra text. Write every value (Q, A, WHY, UNIT, SUMMARY) in the same language as the question on screen:
For QUESTION:
WORK: <for rules (נכון / לא נכון / לא ניתן לדעת), calculations, sequences, list filtering, symbol chains, rotations and cube nets: the computation itself, step by step, max 40 words.
  Finish it before you write ANSWER; ANSWER, A and WHY must state the final result of WORK, with no second thoughts. Otherwise ->
ANSWER: <option label exactly as on screen, e.g. א/ב/ג/ד or 1/2/3/4; for FORMAT typed: the value to type (number or word);
  for FORMAT order: all labels in the correct order joined by " ← " (first ← ... ← last); for FORMAT multi: every correct label joined by " + ">
FORMAT: <choice (pick one option) | typed (an input box, no options) | order (arrange items in order) | multi ("סמן את כל ה..." / select all that apply)>
KIND: question
NUM: <question number if visible, else ->
Q: <the question, cleaned, max 20 words>
A: <the answer itself, max 4 words>
WHY: <one short line, the key step, max 12 words; for situational judgment, max 15 words: why this action is the best>
CONF: <high or low — low if the OCR/image is unclear or you are unsure>
TRAP: <only if one wrong option is clearly built to lure a quick solver (partial calculation, reversed relation, misread axis, the obvious-looking pick): "<label> — <why it is tempting and wrong, max 12 words>"; otherwise ->
For INSTRUCTIONS:
KIND: instructions
UNIT: <unit name, 1-3 words, e.g. אנלוגיות>
NUM: <unit number if visible, else ->
SUMMARY: <what to do in this unit, one sentence>
VISUAL: <yes if questions in this unit are shapes/matrices/graphs, else no>
PASSAGE: <yes if this screen is a reading passage for following questions, else no>
For SELF_REPORT (never suggest, rank or hint which option to choose — only make the statement easy to grasp at a glance):
KIND: self_report
PLAIN: <WHAT it is about: the core content as a very short, everyday Hebrew phrase in first person, about 4-7 words
  (up to 9 only to keep a condition or qualifier). Strip every wrapper — "באיזו תדירות", "נכון לומר ש", "עד כמה",
  "האם", "קרה ש" belong to ASK, not here. Resolve negation and double negation to the plain positive content
  ("לא נכון לומר שמעולם לא היה מצב שבו הקפדת על כללים" -> "הקפדתי על כללים"). Use simple words, but keep the meaning:
  keep conditions that change it ("בלי פיקוח", "בלי רשות", "לצורך אישי", "גם במצב לא נוח", "כי חשבתי שזה לא חשוב") and
  every qualifier word (לא, מעולם, אף פעם, תמיד, בדרך כלל, לעיתים, לפעמים, רק, ללא, בלי). No question mark.
  Exception: when the options are a FREQUENCY scale (אף פעם ... תמיד) and the statement itself also states a frequency
  ("רק לעיתים נדירות", "לרוב", "בדרך כלל"), leave that frequency out of PLAIN — the scale asks it — and keep the behaviour
  ("רק לעיתים נדירות לא דיווחתי על תקלה שגרמתי כשהייתי בטוח שלא ישימו לב" -> "לא דיווחתי על תקלה שגרמתי כשחשבתי שלא ישימו לב").
  Keep the circumstances exactly: "כש..." stays "כש..." (never add "גם"), and keep conditions such as "לא הייתה ברירה",
  "רק אם", "בלי לבדוק" ("היו מצבים שלא הייתה לך ברירה אלא לא לציין שעות שלא עבדת" -> "נאלצתי לדווח שעות שלא עבדתי").
  Examples: "קרה שהצגתי מצב בצורה טובה יותר ממה שהיה באמת כדי להימנע מביקורת" -> "ייפיתי מצב כדי לא לקבל ביקורת";
  "באיזו תדירות נכון לומר שאני מקפיד על כללים גם כשאף אחד אינו בודק אותי?" -> "מקפיד על כללים גם בלי פיקוח";
  "לדעתך מתנה קטנה מלקוח אינה בעייתית" -> "מתנה קטנה מלקוח זה בסדר (לדעתי)".>
MEANINGS: <for EVERY option on screen, in the same order as OPTIONS, what the reader says about THIS statement if they pick
  it — a short plain first-person line (3-8 words), separated by " | ". Translate every option the same neutral way; never
  mark, rank, praise or warn about any option; no words like "נכון", "רצוי", "מומלץ", "בעייתי". For a resolved double
  negation translate against the positive content (מסכים -> "כן, זה קרה לי"). Examples for "מקפיד על כללים גם בלי פיקוח":
  "אני תמיד מקפיד, גם כשאף אחד לא בודק | בדרך כלל אני מקפיד | לפעמים כן, לפעמים לא | לרוב אני לא מקפיד כשאין פיקוח |
  אני לא מקפיד כשאין פיקוח"; for frequency "ייפיתי מצב...": "זה לא קרה לי | קרה פעם-פעמיים | קורה מדי פעם | קורה לי הרבה |
  אני עושה את זה כל פעם".>
ASK: <HOW to answer, matching the on-screen options, exactly one of: "עד כמה אתה מסכים?" (agreement scale),
  "כמה פעמים זה קרה / קורה לך?" (frequency), "כן או לא?" (yes/no), "זה נכון לגביך?" (true / not true for me)>
OPTIONS: <every response option visible on screen, exactly as written, in on-screen order, separated by " | ">
NEG: <yes if the original wording contains a negation, else no>
QUALIFIERS: <meaning-bearing words from the STATEMENT itself (not from the answer options) that must survive in PLAIN:
  any of לפעמים, תמיד, בדרך כלל, מעולם, אף פעם, לעיתים, רק that appear in the statement, separated by " | ";
  leave out "מעולם" only when it is part of a double negation you resolved; "-" if none>
Copy each listed qualifier into PLAIN word for word (do not swap לפעמים for לעיתים or drop it).
For OTHER:
KIND: other

""" + GUIDE


def read(name):
    try:
        return open(os.path.join(CONF, name)).read().strip()
    except OSError:
        return ""


# "cannot tell" as the simulators (and OCR) spell it
RULES_RE = re.compile(r"(לא|אי)[- ]?(ניתן|אפשר) (לדעת|לקבוע|להסיק)|אין (מספיק )?(מידע|נתונים)")
def gemini(key, model, text, image, context, strong=False):
    parts = []
    if image:
        parts.append({"inline_data": {"mime_type": "image/png", "data": image}})
    parts.append({"text": (f"CONTEXT:\n{context}\n\n" if context else "") + "SCREEN OCR:\n" + text})
    # strong: fixed thinking budget + room for the reply (with no cap, Pro spent the whole output budget thinking -> empty reply)
    gen = {"maxOutputTokens": 2500} if not strong else {"maxOutputTokens": 12000, "thinkingConfig": {"thinkingBudget": 4096}}
    if not strong:   # true/false/cannot-tell logic needs more reasoning than a lookup question
        rules = bool(RULES_RE.search(text))
        gen["thinkingConfig"] = {"thinkingBudget": 3072 if rules else 1024}
        gen["maxOutputTokens"] = 5000 if rules else gen["maxOutputTokens"]
    body = {"system_instruction": {"parts": [{"text": PROMPT}]},
            "contents": [{"role": "user", "parts": parts}], "generationConfig": gen}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode(), headers={"content-type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=15 if not strong else 75) as r:
        j = json.load(r)
    return "".join(p.get("text", "") for c in j.get("candidates", [])
                   for p in c.get("content", {}).get("parts", []) if not p.get("thought")).strip()


# Words that flip or limit the meaning of a self-report statement. KEY = these words exactly as they appear in PLAIN
# (with a one-letter prefix such as ש/ו), so the app can show them in bold. Computed here, not by the model.
KEY_WORDS = {"לא", "אין", "איני", "אינני", "בלי", "ללא", "מעולם", "אף", "אי", "פעם", "תמיד", "רק", "לפעמים", "לעיתים",
             "קרובות", "רחוקות", "בדרך", "כלל", "כמעט", "קרה"}
def key_words(plain):
    out = []
    ws = [w.strip(".,?!:;\"'׳״()") for w in plain.split()]
    for i, w in enumerate(ws):
        base = w if w in KEY_WORDS else (w[1:] if len(w) > 2 and w[0] in "שוכ" and w[1:] in KEY_WORDS else "")
        if not base: continue
        # words that only count as part of a pair: אף פעם / אי פעם / בדרך כלל / לעיתים קרובות
        pair = {"אף": "פעם", "אי": "פעם", "בדרך": "כלל"}
        if base in pair and (i + 1 >= len(ws) or ws[i + 1] != pair[base]): continue
        if base == "פעם" and (i == 0 or ws[i - 1].lstrip("שוכ") not in ("אף", "אי")): continue
        if base == "כלל" and (i == 0 or ws[i - 1].lstrip("שוכ") != "בדרך"): continue
        if base in ("קרובות", "רחוקות") and (i == 0 or ws[i - 1].lstrip("שוכ") != "לעיתים"): continue
        if w not in out: out.append(w)
    return out
HESITATION = re.compile(r"רגע[:,!. ]|בעצם |טעות|\bwait\b|\bactually\b", re.I)
LABELS = "אבגדהABCDE12345"
# A choice label is one Hebrew/Latin letter or a 1-2 digit number, alone or followed by a separator ("ב", "ב.", "ב (48)", "12").
LABEL_RE = re.compile(r"^([א-ת]|[A-Ea-e]|\d{1,2})(?=$|[\s.)\]:—–'׳\"״-])")
def tidy(out):
    """Models sometimes drop the ANSWER line or write 'ב.' — normalise so the app always gets a clean label."""
    lines = [l.strip().replace("**", "") for l in out.splitlines() if l.strip()]
    f = {l.split(":", 1)[0].strip().upper(): l.split(":", 1)[1].strip() for l in lines if ":" in l}
    if f.get("KIND", "").lower() == "self_report":   # only the meaning and the on-screen options ever leave the server
        f["KIND"] = "self_report"
        f["KEY"] = " | ".join(key_words(f.get("PLAIN", ""))) or "-"   # the app shows these words in bold
        # MEANINGS = what each option says about this statement. Kept only if there is one per option and none of them
        # evaluates an option (the reader chooses; the app only translates).
        mean = [x.strip() for x in f.get("MEANINGS", "").split("|")]
        opts = [x.strip() for x in f.get("OPTIONS", "").split("|") if x.strip()]
        if len(mean) != len(opts) or not all(mean) or any(w in f.get("MEANINGS", "") for w in ("מומלץ", "רצוי", "עדיף", "התשובה הנכונה")):
            f.pop("MEANINGS", None)
        return "\n".join(f"{k}: {f[k]}" for k in ("KIND", "PLAIN", "KEY", "OPTIONS", "MEANINGS", "ASK", "NEG", "QUALIFIERS") if k in f)
    if f.get("KIND", "").lower() != "question":
        return "\n".join(lines)   # instructions / other pass through
    f["KIND"] = "question"
    if "CONF" in f: f["CONF"] = f["CONF"].lower()   # the re-check below keys on "CONF: low" exactly
    if HESITATION.search(f.get("WHY", "") + " " + f.get("TRAP", "")):   # the model changed its mind mid-line: its ANSWER may be the earlier guess
        f["CONF"] = "low"
    fmt = f.get("FORMAT", "").strip().lower()
    if fmt in ("typed", "order", "multi"):
        f["FORMAT"] = fmt
        lab = f.get("ANSWER", "").strip()
        if fmt == "order":
            parts = [p.strip(" .)(") for p in re.split(r"\s*(?:←|<-|→|->|,)\s*", lab) if p.strip(" .)(")]
            lab = " ← ".join(parts)
        elif fmt == "multi":
            parts = [p.strip(" .)(") for p in re.split(r"\s*(?:\+|,|&| ו-?)\s*", lab) if p.strip(" .)(")]
            lab = " + ".join(parts)
        f["ANSWER"] = lab
        order = ["ANSWER", "FORMAT", "KIND", "NUM", "Q", "A", "WHY", "CONF", "TRAP"]
        return "\n".join(f"{k}: {f[k]}" for k in order if k in f)
    if fmt: f["FORMAT"] = "choice"
    lab = f.get("ANSWER", "").strip(" .)(")
    if not lab and f.get("A", "")[:1] in LABELS and f.get("A", "")[1:2] in (".", ")", " ", ""):
        lab = f["A"][0]; f["A"] = f["A"][1:].strip(" .)")
    m = LABEL_RE.match(lab)   # "ב (48)" -> "ב"; "42" without a FORMAT line stays "42", not "4"
    f["ANSWER"] = m[1].upper() if m else lab
    order = ["ANSWER", "FORMAT", "KIND", "NUM", "Q", "A", "WHY", "CONF", "TRAP"]
    return "\n".join(f"{k}: {f[k]}" for k in order if k in f)


MUST_KEEP = ["לפעמים", "תמיד", "בדרך כלל", "מעולם", "אף פעם", "לעיתים", "רק"]
RESOLVED = re.compile(r"^(קרה ש|יש מצבים ש|לפעמים |היה מצב ש|האם קרה ש)")
UNRESOLVED = re.compile(r"לא נכון (לומר )?ש|אין זה נכון ש")
def self_report_fix(out):
    """SELF_REPORT: what is wrong with PLAIN, as a correction for one retry ("" = fine)."""
    f = {l.split(":", 1)[0].strip().upper(): l.split(":", 1)[1].strip() for l in out.splitlines() if ":" in l}
    if f.get("KIND", "").lower() != "self_report":
        return ""
    plain = f.get("PLAIN", "")
    if UNRESOLVED.search(plain):
        return "your PLAIN still contains the double negation. Rewrite it as the positive meaning (\"קרה ש...\")."
    q = [w.strip() for w in f.get("QUALIFIERS", "").split("|") if w.strip() in MUST_KEEP]
    if RESOLVED.search(plain) or f.get("NEG", "").lower() == "yes":   # a resolved "מעולם לא ... לא" no longer has its מעולם / אף פעם
        q = [w for w in q if w not in ("מעולם", "אף פעם")]
    # whole word (a one-letter prefix like ש/ו/ב is fine), not a substring: "רק" inside "מרקד" does not count
    miss = [w for w in q if not re.search(rf"(?<![א-ת])[א-ת]?{re.escape(w)}(?![א-ת])", plain)]
    return f"your PLAIN dropped {', '.join(miss)}. Rewrite PLAIN keeping these words exactly." if miss else ""


PUNCT = ".,?!:;\"'׳״()[]־-–—"
def mark_same(out, screen):
    """SELF_REPORT: add "SAME: yes" when PLAIN is the statement as written on screen (same words, same order), so the app does not
    make the reader read the same sentence twice. Word-level match against the OCR text; no model call."""
    f = {l.split(":", 1)[0].strip().upper(): l.split(":", 1)[1].strip() for l in out.splitlines() if ":" in l}
    if f.get("KIND", "").lower() != "self_report" or not f.get("PLAIN") or not screen:
        return out
    import difflib
    toks = lambda t: [w for w in (x.strip(PUNCT) for x in t.split()) if w]
    p, t = toks(f["PLAIN"]), toks(screen)
    blocks = [b for b in difflib.SequenceMatcher(None, p, t, autojunk=False).get_matching_blocks() if b.size]
    same = False
    if p and blocks:
        matched = sum(b.size for b in blocks)
        span = blocks[-1].b + blocks[-1].size - blocks[0].b      # the matched words must sit together on screen
        same = matched == len(p) and span <= len(p) + 1   # every word, in order, with at most one extra word between them
    ask = f.get("ASK") or ask_for(f.get("OPTIONS", "") or screen)
    return out + f"\nSAME: {'yes' if same else 'no'}" + ("" if f.get("ASK") else f"\nASK: {ask}")


def ask_for(opts):
    """SELF_REPORT: the short "how to answer" line, derived from the answer options (no model call)."""
    if "מסכים" in opts: return "עד כמה אתה מסכים?"
    if "נכון לגבי" in opts: return "זה נכון לגביך?"
    if any(w in opts for w in ("אף פעם", "לעיתים", "לפעמים", "תמיד")): return "כמה פעמים זה קרה / קורה לך?"
    return "כן או לא?"


VOTERS = os.environ.get("SR_VOTERS", "gemini-pro-latest,gemini-3.8-flash,gemini-flash-latest").split(",")
def vote(key, args):
    """Questions with drawings (shapes, rotations, cubes, matrices): three models answer in parallel; the majority wins.
    No majority -> the strongest model's reply, marked CONF: low so the app shows "לבדוק". Not a question -> first reply."""
    from concurrent.futures import ThreadPoolExecutor
    def one(m):
        try: return tidy(gemini(key, m, *args, strong=True))
        except Exception as e:
            print(f"vote {m} {type(e).__name__}", flush=True); return ""
    with ThreadPoolExecutor(len(VOTERS)) as ex: outs = list(ex.map(one, VOTERS))
    got = [(o, {l.split(":", 1)[0].strip(): l.split(":", 1)[1].strip() for l in o.splitlines() if ":" in l}) for o in outs if "KIND:" in o]
    if not got: return first_ok(key, PRIMARY, *args, strong=True)
    qs = [(o, f) for o, f in got if f.get("KIND", "").lower() == "question" and f.get("ANSWER")]
    if not qs: return got[0][0], ""
    labels = [f["ANSWER"] for _, f in qs]
    best = max(set(labels), key=labels.count)
    print(f"vote {labels} -> {best if labels.count(best) >= 2 else 'no majority'}", flush=True)
    if labels.count(best) >= 2:
        return next(o for o, f in qs if f["ANSWER"] == best), ""
    o = qs[0][0]   # VOTERS[0] (strongest) first in order
    return re.sub(r"(?m)^CONF:.*$", "CONF: low", o) if "CONF:" in o else o + "\nCONF: low", ""


def first_ok(key, models, *a, **kw):
    """Busy/quota/unknown model -> next model. Returns (text, error)."""
    err = ""
    for m in models:
        if blocked.get(m, 0) > time.time():
            if not err:   # every model may be over quota: say so instead of returning an empty body
                err = f"Model error 429: all models over quota, retry in {int(min(blocked[x] for x in models if x in blocked) - time.time()) + 1}s"
            continue
        if not count_call(m):
            return error_reply("limit", LIMIT_MSG), ""
        try:
            out = tidy(gemini(key, m, *a, **kw))
            if "KIND:" in out:
                return out, ""
            err = "Model gave no usable reply"
            print(f"{m} unusable reply", flush=True)
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            err = f"Model error {e.code}: {body[:200]}"
            # prepaid credit used up (402, or 429/403 that talks about billing/credit): not a "busy" state, retrying is pointless
            if e.code == 402 or (e.code in (403, 429) and re.search(r"credit|billing|prepa", body, re.I) and "retry in" not in body):
                print(f"{m} HTTP {e.code} credit", flush=True)
                return error_reply("credit", CREDIT_MSG), ""
            if e.code == 429:   # remember until quota resets; per-minute limits come back fast, daily ones in hours
                t = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?([\d.]+)s", body)
                wait = (int(t[1] or 0) * 3600 + int(t[2] or 0) * 60 + float(t[3])) if t else 60
                blocked[m] = time.time() + wait
            print(f"{m} HTTP {e.code}", flush=True)   # journalctl -u screenreader-proxy (no question text)
            if e.code not in (400, 404, 429, 500, 503):
                break
        except Exception as e:
            err = f"Model error: {e}"
            print(f"{m} {type(e).__name__}: {e}", flush=True)
    return "", err


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.reply(200, "ok" if read("llm_key") else "no key")

    def do_POST(self):
        ip = self.client_address[0]
        now = time.time()
        hits[ip] = [t for t in hits.get(ip, []) if now - t < 60] + [now]
        if len(hits[ip]) > RATE_PER_MIN:                       # one person practising sends a few screens a minute
            return self.reply(429, "too many requests")
        if int(self.headers.get("content-length", 0) or 0) > MAX_BODY:
            return self.reply(413, "request too large")
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
        if not isinstance(q, dict):
            return self.reply(400, "bad json")
        args = (q.get("text", ""), q.get("image"), q.get("context", ""))
        ck = hashlib.sha256(json.dumps([args, bool(q.get("visual"))], ensure_ascii=False).encode()).hexdigest()
        if ck in cache:                                        # same screen again (refresh, back, re-read): no new model call
            return self.reply(200, cache[ck])
        self.send_response(200)
        self.send_header("content-type", "text/plain; charset=utf-8")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        out, err = vote(key, args) if q.get("visual") else first_ok(key, PRIMARY, *args, strong=True)
        fix = self_report_fix(out)
        if fix:   # one corrective retry: PLAIN must keep every meaning-bearing qualifier and resolve double negation
            text, image, ctx = args
            again, _ = first_ok(key, PRIMARY, text, image, f"{ctx}\nCORRECTION: {fix}", strong=True)
            ok = bool(again) and "KIND: self_report" in again and not self_report_fix(again)
            if ok: out = again
            print(f"self_report retry -> {'fixed' if ok else 'not fixed'}", flush=True)
        out = mark_same(out, args[0] if isinstance(args[0], str) else "")
        if out and "KIND:" in out:
            cache[ck] = out
            while len(cache) > 500: cache.pop(next(iter(cache)))
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
