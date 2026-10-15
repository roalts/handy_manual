// web-react/dev/screenshots.mjs adapted to the real API (003) and real answers, for the React build.
// Same checks: console errors, horizontal overflow, small or overlapping tap targets, WCAG AA
// contrast, withheld values, storage, the 2 s first screen on Slow 4G and the 170 kB first load.
// Differences from the mock walkthrough, because real answers aren't the mock's canned ones:
// - Withheld values: the HCP-200 rated head is OCR-verified in ds_0028, so it may be shown.
//   Instead, HV-PROC-07's drive parameter and test points must never be on screen for a user
//   without cert-hv (u01, u03, u09).
// - The HCP-200 scan is opened from its citation chip; no passage holds an unverified marker.
// - Not visible: NK-600 manual 8.4 (SOP-020, restricted) for u01. Page without image: NK-600
//   page 11 for u06. The mock's VRS-75 oil answer (steps, stale, undecided conflict) is asked
//   for real by u03.
// - q04 has no conflict on real data (both bulletins apply); the conflict is checked on u09's
//   BX-12 belt answer instead.
// - Draft with no machine: u09's BX-12 suggestion names none, so the machine field gets
//   GDN-V-9999 (unknown) and then GDN-V-0241. Its part needs approval that no EU lead can give,
//   so the part is removed to reach the direct Servio submit.
// - Not covered: the mock's "slow" and "fail" keywords (17-pending-slow, 18-error-503,
//   24-cancel-question-back). The composer-empties-on-send check runs on a real ask instead.
//
//   WEB_DIR=web-react/dist uv run python tests/api/serve_scratch.py --port 8010 &
//   node web-react/dev/screenshots_real.mjs [--base http://localhost:8010] [--out specs/004-mobile-web-client/screenshots-react-real]
//
// Set CHROME=/path/to/chrome if Chrome isn't in /Applications. Light theme only.

import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const BASE = arg("base", "http://localhost:8010");
const OUT = arg("out", "specs/004-mobile-web-client/screenshots-react-real");
const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9334;
const WIDTH = 375;
const HEIGHT = 812;
const ANSWER_MS = 60000;
// HV-PROC-07 (VRS-110 drive fault reset, restricted) markers: never on screen without cert-hv.
const WITHHELD = ["P9.01", "TP1", "TP2", "Rst En"];
const CERT_HV = new Set(["u02", "u07", "u08"]);
let user = null;
const CONFIRM_SEL = "[role=alertdialog]";
const CONFIRM_BUTTON = "[role=alertdialog] button";
const CONFIRM = JSON.stringify(CONFIRM_SEL);
const SLOW_4G = { offline: false, latency: 562.5, downloadThroughput: 1.44e6 / 8, uploadThroughput: 675e3 / 8 };
const FIRST_SCREEN_MS = 2000;
const FIRST_LOAD_GZIP_BYTES = 170_000;
const CUR = "(document.getElementById('answer-heading')?.closest('.turn') ?? document.body)";

mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const chrome = spawn(CHROME, [
  "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), "copilot-cdp-"))}`,
  "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--hide-scrollbars", "about:blank",
], { stdio: "ignore" });

async function connect() {
  for (let i = 0; i < 50; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return new Promise((resolve, reject) => {
        const ws = new WebSocket(page.webSocketDebuggerUrl);
        ws.onopen = () => resolve(ws);
        ws.onerror = reject;
      });
    } catch { /* Chrome still starting */ }
    await sleep(200);
  }
  throw new Error("Chrome did not start");
}

const ws = await connect();
let seq = 0;
const waiting = new Map();
const problems = [];
const notes = [];
const consoleErrors = [];
const asks = [];
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && waiting.has(msg.id)) {
    const { resolve, reject } = waiting.get(msg.id);
    waiting.delete(msg.id);
    msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
  } else if (msg.method === "Runtime.exceptionThrown") {
    consoleErrors.push(msg.params.exceptionDetails.exception?.description ?? msg.params.exceptionDetails.text);
  } else if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") {
    consoleErrors.push(msg.params.args.map((a) => a.value ?? a.description).join(" "));
  } else if (msg.method === "Log.entryAdded" && msg.params.entry.level === "error") {
    const e = msg.params.entry;
    // Expected HTTP failures exercised on purpose (401 probe, 403 not visible, 422 unknown machine).
    if (!/status of (401|403|404|422)/.test(e.text)) consoleErrors.push(`${e.text} ${e.url ?? ""}`);
  }
};
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++seq;
  waiting.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params }));
});
const evaluate = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(`${expression}: ${r.exceptionDetails.exception?.description}`);
  return r.result.value;
};
const waitFor = async (expression, timeout = 15000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await evaluate(`Boolean(${expression})`)) return;
    await sleep(100);
  }
  throw new Error(`timed out waiting for ${expression}`);
};
const viewport = (height = HEIGHT) => send("Emulation.setDeviceMetricsOverride",
  { width: WIDTH, height, deviceScaleFactor: 2, mobile: true });

async function shot(name, { full = true } = {}) {
  await sleep(150);
  const y = await evaluate("window.scrollY");
  const h = await evaluate("window.scrollTo(0, 0), Math.ceil(document.documentElement.scrollHeight)");
  await viewport(Math.max(HEIGHT, h));
  await sleep(150);
  await checkLayout(name);
  if (!full) {
    await viewport();
    await evaluate(`window.scrollTo(0, ${y})`);
    await sleep(150);
  }
  const { data } = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, "base64"));
  if (full) await viewport();
  console.log(`  saved ${OUT}/${name}.png`);
}

async function checkLayout(name) {
  const withheld = CERT_HV.has(user) ? [] : WITHHELD;
  const r = await evaluate(`(() => {
    const overflow = document.documentElement.scrollWidth - ${WIDTH};
    const small = [...document.querySelectorAll('a, button, input, select, textarea, summary')]
      .filter((el) => el.offsetParent !== null && !el.closest('.skip-link, .visually-hidden') && !el.matches('a.unverified, .page-link'))
      .map((el) => [el, (el.matches('input[type=checkbox], input[type=radio]') && el.closest('label') || el).getBoundingClientRect()])
      .filter(([, b]) => b.width > 0 && (b.height < 43.5 || b.width < 43.5))
      .map(([el, b]) => el.tagName + '.' + el.className + ' "' + (el.textContent || el.value || '').trim().slice(0, 30) + '" ' + Math.round(b.width) + 'x' + Math.round(b.height));
    const text = document.body.innerText;
    const junk = (text.match(/\\b(null|undefined|NaN|\\[object Object\\])\\b/g) || []);

    const modal = [...document.querySelectorAll('[role=dialog], [role=alertdialog], dialog[open]')].filter((e) => e.getClientRects().length).pop();
    const scope = modal ?? document.body;
    const closed = (el) => { const d = el.closest('details'); return d && !d.open && !el.closest('summary'); };
    const live = (el) => !el.closest('[inert], .visually-hidden, .sr-only, .skip-link') && !closed(el) && el.getClientRects().length > 0;
    const name = (el) => (el.getAttribute('aria-label') || el.textContent || el.placeholder || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
    const layer = (el) => { for (let e = el.parentElement; e; e = e.parentElement) if (/sticky|fixed/.test(getComputedStyle(e).position)) return e; return null; };
    const boxes = (el) => getComputedStyle(el).display === 'inline' ? [...el.getClientRects()] : [el.getBoundingClientRect()];
    const rects = [...scope.querySelectorAll('a, button, summary, textarea, input, select')].filter(live).map((el) => [el, boxes(el), layer(el)]);
    const overlap = [];
    for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) {
      const [a, ras, la] = rects[i], [b, rbs, lb] = rects[j];
      if (a.contains(b) || b.contains(a) || la !== lb) continue;
      for (const ra of ras) for (const rb of rbs) {
        const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left), h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
        if (w > 0.5 && h > 0.5) overlap.push('"' + name(a) + '" and "' + name(b) + '" by ' + Math.round(w) + 'x' + Math.round(h));
      }
    }
    const parse = (c) => {
      let m = c.match(/^rgba?\\(([^)]+)\\)/);
      if (m) { const p = m[1].split(/[\\s,\\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p[3] ?? 1]; }
      m = c.match(/^color\\(srgb ([^)]+)\\)/);
      if (m) { const p = m[1].split(/[\\s\\/]+/).filter(Boolean).map(Number); return [p[0] * 255, p[1] * 255, p[2] * 255, p[3] ?? 1]; }
      return null;
    };
    const over = (top, under) => { const a = top[3]; return [0, 1, 2].map((i) => top[i] * a + under[i] * (1 - a)).concat(1); };
    const bgOf = (el) => {
      const layers = [];
      for (let e = el; e; e = e.parentElement) {
        const c = parse(getComputedStyle(e).backgroundColor);
        if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
      }
      let bg = [255, 255, 255, 1];
      for (const l of layers.reverse()) bg = over(l, bg);
      return bg;
    };
    const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
    const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
    const contrast = [];
    const check = (el, color, label) => {
      const cs = getComputedStyle(el);
      const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700;
      const fg = parse(color); if (!fg) return;
      const bg = bgOf(el);
      const r = ratio(over(fg, bg), bg);
      const need = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5;
      if (r < need) contrast.push(label + ' ' + r.toFixed(2) + ':1 (needs ' + need + ')');
    };
    for (const el of [...scope.querySelectorAll('*')].filter((el) => live(el) && !el.closest(':disabled') && getComputedStyle(el).backgroundClip !== 'text' && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()))) {
      check(el, getComputedStyle(el).color, el.tagName.toLowerCase() + '.' + el.className + ' "' + name(el).slice(0, 24) + '"');
    }
    for (const t of scope.querySelectorAll('textarea[placeholder], input[placeholder]')) if (live(t) && !t.value) check(t, getComputedStyle(t, '::placeholder').color, 'placeholder "' + t.placeholder + '"');
    return { overflow, small, junk, overlap, contrast, leaked: ${JSON.stringify(withheld)}.filter((v) => text.includes(v)) };
  })()`);
  for (const j of r.junk) problems.push(`${name}: stray "${j}" on screen`);
  if (r.overflow > 0) problems.push(`${name}: horizontal overflow ${r.overflow}px`);
  for (const s of r.small) problems.push(`${name}: tap target under 44px: ${s}`);
  for (const s of r.overlap) problems.push(`${name}: tap targets overlap: ${s}`);
  for (const s of r.contrast) problems.push(`${name}: contrast ${s}`);
  for (const v of r.leaked) problems.push(`${name}: withheld value on screen for ${user}: ${v}`);
}

const click = (selector, text, root = "document") => evaluate(`(() => {
  const el = [...${root}.querySelectorAll(${JSON.stringify(selector)})].find((e) => e.textContent.includes(${JSON.stringify(text ?? "")}));
  if (!el) throw new Error('no ${selector} with ${text ?? ""}');
  el.click();
})()`);
const has = (selector, text = "", root = "document") =>
  evaluate(`[...${root}.querySelectorAll(${JSON.stringify(selector)})].some((e) => e.textContent.includes(${JSON.stringify(text)}))`);
const textOf = (root = CUR) => evaluate(`(${root}).innerText`);
/** Taps a clarify option, then waits for the new latest answer (no turn is `answer-heading` while pending). */
async function pick(text) {
  await evaluate("document.getElementById('answer-heading')?.setAttribute('data-before', '')");
  await click(".btn.option", text, CUR);
  await waitFor("document.querySelector('#answer-heading:not([data-before]), .card.error:not([data-before])')", ANSWER_MS);
}

async function go(hash) {
  await evaluate(`location.hash = ${JSON.stringify(hash)}`);
  await sleep(100);
}

async function signInAs(userId) {
  if (await evaluate("Boolean(document.querySelector('.user-bar button'))")) await click(".user-bar button", "Sign out");
  await waitFor(`document.querySelector('.user-list')`);
  await click(".btn.user", userId);
  await waitFor(`document.querySelector('.composer')`);
  user = userId;
}

/** Asks, then waits for `done` to match something new. Returns the answer's status and seconds. */
async function askQuestion(q, done = "#answer-heading, .card.error") {
  const fresh = JSON.stringify(done.split(",").map((s) => `${s.trim()}:not([data-before])`).join(", "));
  const start = Date.now();
  await evaluate(`(() => { for (const el of document.querySelectorAll(${JSON.stringify(done)})) el.setAttribute('data-before', '');
    const t = document.getElementById('question'); t.value = ${JSON.stringify(q)};
    t.dispatchEvent(new Event('input', { bubbles: true })); t.form.requestSubmit(); })()`);
  await waitFor(`document.querySelector(${fresh})`, ANSWER_MS);
  const status = await evaluate(`(() => { const t = ${CUR}; return t.querySelector('.card.restricted') ? 'restricted'
    : t.querySelector('.clarify') ? 'clarify' : t.querySelector('.card.abstain, .abstain') ? 'abstain'
    : document.querySelector('.card.error:not([data-before])') ? 'error' : 'answered'; })()`);
  const seconds = (Date.now() - start) / 1000;
  asks.push({ user, q, status, seconds });
  console.log(`  ${user} "${q}": ${status} in ${seconds.toFixed(1)} s`);
  return status;
}

const expect = async (cond, problem) => { if (!(await cond)) problems.push(problem); };

await send("Page.enable");
await send("Runtime.enable");
await send("Log.enable");
await viewport();
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "light" }] });

async function firstLoad() {
  await send("Network.enable");
  await send("Network.setCacheDisabled", { cacheDisabled: true });
  await send("Network.emulateNetworkConditions", SLOW_4G);
  const { identifier } = await send("Page.addScriptToEvaluateOnNewDocument", { source: `
    new MutationObserver((_, obs) => {
      if (document.querySelector('.user-list')) { window.__firstScreenMs = performance.now(); obs.disconnect(); }
    }).observe(document, { childList: true, subtree: true });` });
  await send("Page.navigate", { url: `${BASE}/` });
  await waitFor("window.__firstScreenMs", 20000);
  const ms = Math.round(await evaluate("window.__firstScreenMs"));
  const urls = await evaluate(`performance.getEntriesByType('resource').map((e) => e.name)
    .concat([...document.querySelectorAll('script[src], link[rel=stylesheet], link[rel=modulepreload]')].map((e) => e.src || e.href))
    .filter((u) => /[.](m?js|css)$/.test(new URL(u).pathname))`);
  await send("Page.removeScriptToEvaluateOnNewDocument", { identifier });
  await send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await send("Network.setCacheDisabled", { cacheDisabled: false });
  let gz = 0;
  for (const u of [...new Set(urls)]) {
    const body = Buffer.from(await (await fetch(u, { headers: { "Accept-Encoding": "identity" } })).arrayBuffer());
    gz += gzipSync(body, { level: 6 }).length;
  }
  console.log(`  first screen ${ms} ms on Slow 4G; first-load JS and CSS ${(gz / 1000).toFixed(1)} kB gzip in ${new Set(urls).size} files`);
  if (ms > FIRST_SCREEN_MS) problems.push(`first screen took ${ms} ms on Slow 4G (limit ${FIRST_SCREEN_MS} ms)`);
  if (gz > FIRST_LOAD_GZIP_BYTES) problems.push(`first-load JS and CSS is ${(gz / 1000).toFixed(1)} kB gzip (limit ${FIRST_LOAD_GZIP_BYTES / 1000} kB)`);
}

try {
  console.log("first load (Slow 4G, cold cache)");
  await firstLoad();

  console.log("sign-in");
  await send("Page.navigate", { url: `${BASE}/` });
  await waitFor(`document.querySelector('.user-list')`);
  await shot("01-sign-in");

  console.log("q04 casing torque, u01 pump technician; composer empties on send");
  await signInAs("u01");
  await shot("02-ask-empty", { full: false });
  await evaluate(`(() => { const t = document.getElementById('question'); t.value = 'Casing bolt torque for FRS-P-0031 after a seal change';
    t.dispatchEvent(new Event('input', { bubbles: true })); t.form.requestSubmit(); })()`);
  await waitFor("document.querySelector('.card.pending, #answer-heading')");
  if (await evaluate("Boolean(document.querySelector('.card.pending'))")) {
    const sent = await evaluate(`({ box: document.getElementById('question').value,
      bubble: document.querySelector('.card.pending').closest('.turn')?.querySelector('.asked')?.textContent ?? '',
      kept: sessionStorage.getItem('copilot.question') })`);
    if (sent.box !== "") problems.push(`composer not emptied on send: "${sent.box}"`);
    if (!sent.bubble.includes("Casing bolt torque")) problems.push(`pending turn does not show the question: "${sent.bubble}"`);
    if (sent.kept !== "Casing bolt torque for FRS-P-0031 after a seal change") problems.push(`question not kept while pending: "${sent.kept}"`);
  } else notes.push("q04 answered before the pending state could be checked");
  const t0 = Date.now();
  await waitFor("document.getElementById('answer-heading') || document.querySelector('.card.error')", ANSWER_MS);
  asks.push({ user, q: "Casing bolt torque for FRS-P-0031 after a seal change", status: "answered", seconds: (Date.now() - t0) / 1000 });
  await expect(evaluate("sessionStorage.getItem('copilot.question') === null"), "sessionStorage still holds the question after the answer");
  await shot("03-answer-q04");
  await expect(evaluate(`/SB-2025-009/.test(${CUR}.innerText)`), "q04 answer does not show bulletin SB-2025-009");

  console.log("source sheet from the first citation");
  await click("a.chip", "1", CUR);
  await waitFor(`document.getElementById('source-title')`);
  await shot("04-source-bulletin");
  await evaluate("history.back()");
  await waitFor(`document.getElementById('answer-heading') && !document.getElementById('source-title')`);

  console.log("HCP-200 scanned, machine-translated source");
  await askQuestion("Rated head of the HCP-200");
  await shot("05-answer-hcp200-scan");
  await click("a.chip", "1", CUR);
  await waitFor(`document.getElementById('source-title') && document.querySelector('.page-image img')?.complete`, 20000);
  const scan = await textOf("document.querySelector('[role=dialog]')");
  if (!/Scanned page/.test(scan)) problems.push("HCP-200 source does not say it is a scanned page");
  if (!/machine-translated/.test(scan)) problems.push("HCP-200 source does not show the machine translation");
  await shot("06-source-scan-translated");
  await evaluate("history.back()");
  await waitFor(`document.getElementById('answer-heading') && !document.getElementById('source-title')`);

  console.log("not visible: NK-600 8.4 (SOP-020, restricted) for u01");
  await go("#/sources/p_89e01fa9f9431d888616bfd8");
  await waitFor(`document.getElementById('nv-title')`);
  await shot("08-source-not-visible", { full: false });
  await evaluate("history.back()");
  await waitFor(`!document.getElementById('nv-title')`);

  console.log("clarify as u01");
  await go("#/ask");
  await waitFor(`document.getElementById('question')`);
  if (await askQuestion("Casing torque on the HCP-350 at Fresno") === "clarify") {
    await shot("12-clarify");
    await pick("FRS-P-0031");
    await expect(evaluate(`${CUR}.querySelector('.asset-id')?.textContent.includes('FRS-P-0031')`), "clarify pick did not answer for FRS-P-0031");
    const resent = await evaluate(`${CUR}.querySelector('.asked').textContent`);
    if (!resent.includes("HCP-350 at Fresno")) problems.push(`clarify resend lost the question: ${resent}`);
    await shot("12b-clarify-answered");
  } else {
    problems.push("HCP-350 at Fresno: real answer was not a clarification");
    await shot("12-clarify");
  }

  console.log("did you mean, follow-up, new question (u01)");
  const typo = "What's the impeller-to-casing clearance spec on an HCP-20?";
  if (await askQuestion(typo) === "clarify" && await has(".btn.option", "HCP-200", CUR)) {
    await shot("20-did-you-mean");
    await expect(evaluate(`${CUR}.querySelector('.clarify .hint').textContent.includes("isn't in the documents")`), "did-you-mean clarify uses the machine-pick hint");
    await pick("HCP-200");
    await expect(evaluate(`!${CUR}.querySelector('.clarify')`), "did-you-mean tap did not reach an answer");
    const clearance = await textOf();
    if (!/0[.,]38/.test(clearance)) notes.push(`HCP-200 clearance answer: ${clearance.replace(/\s+/g, " ").slice(0, 200)}`);
    await expect(evaluate("Boolean(document.getElementById('new-question'))"), "no New question control while an answer is on screen");
    await shot("21-did-you-mean-answer-follow-up-bar");
  } else {
    problems.push("HCP-20: real answer was not a did-you-mean clarification");
    await shot("20-did-you-mean");
  }
  await click("#new-question", "New question");
  await sleep(100);
  await expect(evaluate("!document.getElementById('answer-heading') && !document.querySelector('.follow-up')"), "New question did not clear the answer");
  await shot("22-new-question-cleared", { full: false });
  await askQuestion(typo);
  await askQuestion("Oh, I meant HCP-200", ".answering, .card.error");
  const answering = await evaluate(`(document.querySelector('.answering:not([data-before])') ?? {}).textContent ?? ''`);
  if (!/Answering: .*HCP-200/.test(answering)) problems.push(`follow-up not shown as read: "${answering}"`);
  await shot("23-follow-up-answering");

  console.log("restricted, abstain, oil as u03 (no high-voltage certification)");
  await signInAs("u03");
  if (await askQuestion("E-31 on TAC-C-0143, how do I reset it?") !== "restricted") problems.push("E-31 on TAC-C-0143 for u03 is not restricted");
  await shot("10-restricted");
  await expect(evaluate(`(${CUR}.querySelector('.missing-groups')?.innerText ?? '').includes("High-voltage electrical certification (VFD cabinets)")`),
    "restricted card does not use the /api/groups description");
  if (await askQuestion("Warranty on the BX-20 conveyor") !== "abstain") problems.push("BX-20 warranty is not an abstain");
  await shot("11-abstain");
  await askQuestion("Which oil for the VRS-75 RTM-C-0121?");
  await shot("09-answer-vrs75-oil");
  const oil = await textOf();
  if (!/superseded/i.test(oil)) problems.push("VRS-75 oil answer does not label its superseded source");
  if (!/possibly out of date/i.test(oil)) problems.push("VRS-75 oil answer does not label its possibly stale source");

  console.log("NK-600 8.3 for u06: page number, no page image");
  await signInAs("u06");
  await go("#/sources/p_f71b980da8173a0d23371f8c");
  await waitFor(`document.getElementById('source-title')`);
  if (await evaluate("Boolean(document.querySelector('.page-image'))")) problems.push("NK-600 page 11 image shown to u06");
  await shot("07-source-shared-page-no-image");
  await evaluate("history.back()");

  console.log("draft from restricted, edit, request approval (u03)");
  await signInAs("u03");
  await askQuestion("E-31 on TAC-C-0143, how do I reset it?");
  await click("button", "Draft a work order", CUR);
  await waitFor(`document.getElementById('wo-summary')`);
  await shot("13-draft-form-needs-approval");
  await evaluate(`(() => { const t = document.getElementById('wo-summary'); t.value = 'E-31 trip on TAC-C-0143, needs reset under HV-PROC-07'; t.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await click("button", "Request approval");
  await waitFor(`document.querySelector('.status-pending_approval')`);
  await shot("14-draft-pending-approval");
  await expect(evaluate("document.body.innerText.includes('Kenji Watanabe (u08)')"), "pending draft does not name the eligible approver");
  const draftHash = await evaluate("location.hash");

  console.log("lead u08 approves with a note; u03 sees it and submits to MaintPro");
  await signInAs("u08");
  await go(draftHash);
  await waitFor(`document.getElementById('wo-note')`);
  await evaluate(`(() => { const t = document.getElementById('wo-note'); t.value = 'Approved, Daniel Reyes is booked for Thursday'; t.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await shot("14b-draft-approver-view");
  await click("button", "Approve");
  await waitFor(`document.querySelector('.status-approved')`);
  await signInAs("u03");
  await go(draftHash);
  await waitFor(`document.querySelector('.status-approved')`);
  await shot("14c-draft-approved-with-note");
  await expect(evaluate("document.body.innerText.includes('Note: Approved, Daniel Reyes is booked for Thursday')"), "approved draft does not show the decision note");
  await click("button", "Submit to MaintPro");
  await waitFor(`document.querySelector(${CONFIRM})`);
  await click(CONFIRM_BUTTON, "Send to MaintPro");
  await waitFor(`document.querySelector('.status-submitted')`);

  console.log("u09: BX-12 belt at Gdansk (conflict), draft with no machine, then Servio");
  await signInAs("u09");
  await askQuestion("New BX-12 belt at Gdansk tracks to the left. What do I do?");
  await shot("15a-answer-bx12-gdansk-conflict");
  await expect(has(".conflict", "", CUR), "BX-12 answer shows no conflict");
  const setAsset = (v) => evaluate(`(() => { const t = document.getElementById('wo-asset'); t.value = ${JSON.stringify(v)}; t.dispatchEvent(new Event('input', { bubbles: true })); t.form.requestSubmit(); })()`);
  if (await has("button", "Draft a work order", CUR)) {
    await click("button", "Draft a work order", CUR);
    await waitFor(`document.getElementById('wo-asset') || document.getElementById('wo-summary')`);
    if (await evaluate("Boolean(document.getElementById('wo-asset'))")) {
      await shot("13b-draft-choose-machine");
      await setAsset("GDN-V-9999");
      await waitFor(`document.getElementById('wo-asset-error')`);
      await shot("13c-draft-unknown-machine");
      await expect(evaluate("!document.querySelector('.card.error')"), "unknown machine shown as a page error");
      await expect(evaluate("document.getElementById('wo-asset').value === 'GDN-V-9999'"), "typed machine lost after the error");
      await setAsset("gdn-v-0241");
      await waitFor(`document.getElementById('wo-summary')`);
      await expect(evaluate("document.querySelector('.draft-form').innerText.includes('GDN-V-0241')"), "created draft is not for GDN-V-0241");
    } else notes.push("BX-12: the real suggestion already names a machine, so 13b and 13c are not covered");
    await shot("15b-draft-parts-need-approval");
    // Ordering parts needs approval and no EU lead can approve conveyors: drop the part to submit directly.
    if (!(await has("button", "Submit to Servio")) && await has("button", "Remove")) {
      await click("button", "Remove");
      await click("button", "Save draft");
      await waitFor(`[...document.querySelectorAll('button')].some((b) => b.textContent.includes('Submit to Servio'))`).catch(() => {});
    }
    if (await has("button", "Submit to Servio")) {
      await click("button", "Submit to Servio");
      await waitFor(`document.querySelector(${CONFIRM})`);
      await shot("15-draft-confirm-servio", { full: false });
      await click(CONFIRM_BUTTON, "Send to Servio");
      await waitFor(`document.querySelector('.status-submitted')`);
      await shot("16-draft-submitted");
    } else {
      notes.push(`u09 draft offers no direct Servio submit: ${(await textOf("document.querySelector('[role=dialog]') ?? document.body")).replace(/\s+/g, " ").slice(0, 300)}`);
    }
    await evaluate("history.back()");
  } else notes.push("u09 BX-12 answer offers no draft, so 13b, 13c, 15 and 16 are not covered");

  console.log("expired session keeps the question");
  await signInAs("u03");
  await go("#/ask");
  await waitFor(`document.getElementById('question')`);
  await evaluate("fetch('/api/session', {method: 'DELETE'})");
  await askQuestion("question typed before expiry", ".user-list");
  asks.pop();
  await shot("19-session-expired", { full: false });
  await click(".btn.user", "u03");
  await waitFor(`document.getElementById('question')`);
  const afterExpiry = await evaluate("document.getElementById('question').value");
  if (afterExpiry !== "question typed before expiry") problems.push(`question lost after expiry: "${afterExpiry}"`);

  const stored = await evaluate("JSON.stringify({local: Object.keys(localStorage), session: Object.keys(sessionStorage)})");
  console.log(`storage: ${stored}`);
  const st = JSON.parse(stored);
  if (st.local.length) problems.push(`localStorage used: ${stored}`);
  if (st.session.some((k) => k !== "copilot.question")) problems.push(`sessionStorage holds more than the question: ${stored}`);
} catch (err) {
  problems.push(`run aborted: ${err.message}`);
} finally {
  ws.close();
  chrome.kill();
}

console.log(`\n${asks.length} asks:`);
for (const a of asks) console.log(`  ${a.user} ${a.status} ${a.seconds.toFixed(1)} s  ${a.q}`);
for (const n of notes) console.log(`note: ${n}`);
for (const e of consoleErrors) problems.push(`console error: ${e}`);
if (problems.length) {
  console.log(`\n${problems.length} problem(s):`);
  for (const p of problems) console.log(`  - ${p}`);
  process.exit(1);
}
console.log("\nall screens rendered at 375 px with no console errors, no overflow, no small or overlapping tap targets, text AA, no withheld values");
