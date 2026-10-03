// End-to-end test: local simulator in a real Chrome window -> ScreenReader --e2e (real screen capture,
// OCR, layout, Practice/Claude) -> compare with the simulator's hidden answer. Writes test/e2e-report.{json,md}.
// Usage: node test/e2e.mjs [--only 3,19,21] [--seed 42]
import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const argv = process.argv.slice(2), opt = k => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : null; };
const only = opt('--only')?.split(',').map(Number), seed = opt('--seed') || '42';
const tmp = fs.mkdtempSync('/tmp/sr-e2e-'), fifo = `${tmp}/cmd`, outFile = `${tmp}/out.jsonl`;
const sleep = ms => new Promise(r => setTimeout(r, ms));

// 1. Chrome with remote debugging, fullscreen-ish app window on the main display.
const CH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const chrome = spawn(CH, ['--remote-debugging-port=9333', `--user-data-dir=${tmp}/chrome`, '--no-first-run', '--start-maximized',
  `--app=file://${root}/test/sim/index.html?seed=${seed}`], { stdio: 'ignore' });
let ws;
for (let i = 0; i < 50 && !ws; i++) {
  await sleep(200);
  try { const t = (await (await fetch('http://127.0.0.1:9333/json')).json()).find(t => t.type === 'page'); if (t) ws = new WebSocket(t.webSocketDebuggerUrl); } catch {}
}
await new Promise(r => ws.onopen = r);
let msgId = 0; const pending = {};
ws.onmessage = e => { const m = JSON.parse(e.data); pending[m.id]?.(m); };
const js = expr => new Promise(r => { const id = ++msgId; pending[id] = m => r(m.result?.result?.value); ws.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression: expr, returnByValue: true } })); });
await sleep(1000);
await js('document.documentElement.requestFullscreen?.().catch(()=>{})');

// 2. ScreenReader in e2e mode (launched via `open -n` so macOS attributes Screen Recording to the app).
execSync(`mkfifo ${fifo}`);
execSync('pkill -x ScreenReader || true');
spawn('open', ['-n', '-W', `${root}/ScreenReader.app`, '--args', '--e2e', fifo, outFile], { stdio: 'ignore' });
const cmd = fs.openSync(fifo, 'w');
let seen = 0;
async function run(tag) {
  fs.writeSync(cmd, `go ${tag}\n`);
  for (;;) {
    await sleep(200);
    const lines = fs.existsSync(outFile) ? fs.readFileSync(outFile, 'utf8').trim().split('\n').filter(Boolean) : [];
    if (lines.length > seen) return JSON.parse(lines[seen++]);
  }
}
const parse = a => (a?.match(/ANSWER:\s*\**\s*([A-Dא-ד])/) || [])[1] || null;
const state = () => js('JSON.stringify(window.simState)').then(JSON.parse);
const next = () => js("document.getElementById('next').click()");

// 3. Main pass: every question once, in the simulator's randomized order.
const rows = [], all = JSON.parse(await js('JSON.stringify(window.SIM_QUESTIONS)'));
for (let i = 0; i < all.length; i++) {
  const s = await state();
  if (!only || only.includes(s.id)) {
    await sleep(700);                                   // let the page paint
    const r = await run(`q${s.id}`);
    const got = parse(r.answer);
    rows.push({ q: s.id, type: s.type, sub: s.sub, diff: s.diff, expectedMode: s.type === 'VISUAL' || s.type === 'MIXED' ? 'VISUAL' : 'TEXT',
      mode: r.mode, expected: s.answerLabel, got, correct: got === s.answerLabel, ms: r.ms_total, cached: r.cached, error: r.error, answer: r.answer });
    console.log(`q${s.id} ${s.type}/${s.diff} mode=${r.mode} expected=${s.answerLabel} got=${got} ${got === s.answerLabel ? 'OK' : 'WRONG'} ${r.ms_total}ms`);
  }
  await next();
}

// 4. Behaviour checks.
const checks = [];
const check = (name, ok, detail) => { checks.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name} ${detail}`); };
if (!only) {
  // duplicate: same question again after the timer has moved -> served from cache, same answer
  let s = await state(); await sleep(700); const d1 = await run('dup1'); await sleep(2500); const d2 = await run('dup2');
  check('duplicate question -> cached, no new request', d2.cached === true && parse(d2.answer) === parse(d1.answer), `q${s.id} first=${d1.ms_total}ms second=${d2.ms_total}ms cached=${d2.cached}`);
  // question change: next question must not reuse the previous answer
  await next(); s = await state(); await sleep(700); const c = await run('change');
  check('question change -> new answer for new question', c.cached === false && parse(c.answer) === s.answerLabel, `q${s.id} expected=${s.answerLabel} got=${parse(c.answer)}`);
  // rapid transitions: 3 Next clicks within ~300 ms, then capture -> must answer the final question
  for (let k = 0; k < 3; k++) { await next(); await sleep(100); }
  s = await state(); await sleep(400); const rp = await run('rapid');
  check('rapid transitions -> answers the question on screen', parse(rp.answer) === s.answerLabel, `q${s.id} expected=${s.answerLabel} got=${parse(rp.answer)}`);
}

fs.closeSync(cmd); chrome.kill(); execSync(`rm -rf ${tmp}`);

// 5. Report.
const ok = rows.filter(r => r.correct).length, modeOk = rows.filter(r => r.mode === r.expectedMode).length;
const md = [`# ScreenReader E2E report (seed ${seed})`, '',
  `Answers correct: **${ok}/${rows.length}** · Mode correct: **${modeOk}/${rows.length}** · Checks: **${checks.filter(c => c.ok).length}/${checks.length}**`, '',
  '| # | Type | Sub-type | Difficulty | Detected mode | Expected | ScreenReader | Result | Time |', '|---|---|---|---|---|---|---|---|---|',
  ...rows.map(r => `| ${r.q} | ${r.type} | ${r.sub} | ${r.diff} | ${r.mode}${r.mode === r.expectedMode ? '' : ' ⚠'} | ${r.expected} | ${r.got ?? '—'} | ${r.correct ? 'Correct' : 'Incorrect'} | ${(r.ms / 1000).toFixed(1)} s |`),
  '', '## Behaviour checks', '', ...checks.map(c => `- ${c.ok ? 'PASS' : 'FAIL'} ${c.name} — ${c.detail}`)].join('\n');
fs.writeFileSync(`${root}/test/e2e-report.md`, md + '\n');
fs.writeFileSync(`${root}/test/e2e-report.json`, JSON.stringify({ rows, checks }, null, 1));
console.log(`\nanswers ${ok}/${rows.length}, modes ${modeOk}/${rows.length} -> test/e2e-report.md`);
process.exit(0);
