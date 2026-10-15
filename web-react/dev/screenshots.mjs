// Walks every screen at 375 px in headless Chrome over the DevTools protocol, with no npm packages.
// Fails on console errors, horizontal overflow, small or overlapping tap targets, text under WCAG AA
// contrast, a withheld value on screen, a first screen slower than 2 s on Slow 4G, or more than
// 170 kB gzip of first-load JS and CSS. Works against the React build
// (mock --web web-react/dist). --theme dark emulates prefers-color-scheme: dark.
//
//   uv run python web-react/dev/mock_api.py &           # mock on :8000
//   node web-react/dev/screenshots.mjs [--base http://localhost:8000] [--out specs/004-mobile-web-client/screenshots] [--theme light|dark]
//
// Set CHROME=/path/to/chrome if Chrome isn't in /Applications.

import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const BASE = arg("base", "http://localhost:8000");
const OUT = arg("out", "specs/004-mobile-web-client/screenshots");
const THEME = arg("theme", "light");
const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9333;
const WIDTH = 375;
const HEIGHT = 812;
const WITHHELD = ["45 m", "200 m³/h"]; // HCP-200 rated head: must never be shown as text
// The submit confirmation: a native <dialog> in the plain client, a Radix alert dialog in React.
const CONFIRM_SEL = "dialog[open], [role=alertdialog]";
const CONFIRM_BUTTON = "dialog[open] button, [role=alertdialog] button";
const CONFIRM = JSON.stringify(CONFIRM_SEL);
// Chrome DevTools "Slow 4G" preset: 562.5 ms latency, 1.44 Mbit/s down, 675 kbit/s up.
const SLOW_4G = { offline: false, latency: 562.5, downloadThroughput: 1.44e6 / 8, uploadThroughput: 675e3 / 8 };
const FIRST_SCREEN_MS = 2000;
const FIRST_LOAD_GZIP_BYTES = 170_000;
// The turn holding the latest settled answer in the React thread; the whole page in the plain client.
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
const consoleErrors = [];
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
    // Expected HTTP failures exercised on purpose (401 probe, 403 not visible, 422 unknown machine, 503).
    if (!/status of (401|403|404|422|503)/.test(e.text)) consoleErrors.push(`${e.text} ${e.url ?? ""}`);
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
  // Checked at full height, so the sticky composer doesn't sit over the content it scrolls past.
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
  const r = await evaluate(`(() => {
    const overflow = document.documentElement.scrollWidth - ${WIDTH};
    const small = [...document.querySelectorAll('a, button, input, select, textarea, summary')]
      .filter((el) => el.offsetParent !== null && !el.closest('.skip-link, .visually-hidden') && !el.matches('a.unverified, .page-link'))
      .map((el) => [el, (el.matches('input[type=checkbox], input[type=radio]') && el.closest('label') || el).getBoundingClientRect()])
      .filter(([, b]) => b.width > 0 && (b.height < 43.5 || b.width < 43.5))
      .map(([el, b]) => el.tagName + '.' + el.className + ' "' + (el.textContent || el.value || '').trim().slice(0, 30) + '" ' + Math.round(b.width) + 'x' + Math.round(b.height));
    const text = document.body.innerText;
    const junk = (text.match(/\\b(null|undefined|NaN|\\[object Object\\])\\b/g) || []);

    // Overlap and contrast, as in mockups.mjs. With a dialog open only the top dialog counts: the
    // page behind it is covered and hidden from assistive tech.
    const modal = [...document.querySelectorAll('[role=dialog], [role=alertdialog], dialog[open]')].filter((e) => e.getClientRects().length).pop();
    const scope = modal ?? document.body;
    const closed = (el) => { const d = el.closest('details'); return d && !d.open && !el.closest('summary'); };
    const live = (el) => !el.closest('[inert], .visually-hidden, .sr-only, .skip-link') && !closed(el) && el.getClientRects().length > 0;
    const name = (el) => (el.getAttribute('aria-label') || el.textContent || el.placeholder || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
    // A link that wraps is compared line by line. A sticky or fixed bar is meant to lie over the
    // content scrolling under it, so only controls in the same layer are compared.
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
    // Disabled controls are exempt from WCAG 1.4.3; gradient-clipped text (the loading shimmer) can't be measured this way.
    for (const el of [...scope.querySelectorAll('*')].filter((el) => live(el) && !el.closest(':disabled') && getComputedStyle(el).backgroundClip !== 'text' && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()))) {
      check(el, getComputedStyle(el).color, el.tagName.toLowerCase() + '.' + el.className + ' "' + name(el).slice(0, 24) + '"');
    }
    for (const t of scope.querySelectorAll('textarea[placeholder], input[placeholder]')) if (live(t) && !t.value) check(t, getComputedStyle(t, '::placeholder').color, 'placeholder "' + t.placeholder + '"');
    return { overflow, small, junk, overlap, contrast, leaked: ${JSON.stringify(WITHHELD)}.filter((v) => text.includes(v)) };
  })()`);
  for (const j of r.junk) problems.push(`${name}: stray "${j}" on screen`);
  if (r.overflow > 0) problems.push(`${name}: horizontal overflow ${r.overflow}px`);
  for (const s of r.small) problems.push(`${name}: tap target under 44px: ${s}`);
  for (const s of r.overlap) problems.push(`${name}: tap targets overlap: ${s}`);
  for (const s of r.contrast) problems.push(`${name}: contrast ${s}`);
  for (const v of r.leaked) problems.push(`${name}: withheld value on screen: ${v}`);
}

const click = (selector, text, root = "document") => evaluate(`(() => {
  const el = [...${root}.querySelectorAll(${JSON.stringify(selector)})].find((e) => e.textContent.includes(${JSON.stringify(text ?? "")}));
  if (!el) throw new Error('no ${selector} with ${text ?? ""}');
  el.click();
})()`);

async function go(hash) {
  await evaluate(`location.hash = ${JSON.stringify(hash)}`);
  await sleep(100);
}

async function signInAs(userId) {
  if (await evaluate("Boolean(document.querySelector('.user-bar button'))")) await click(".user-bar button", "Sign out");
  await waitFor(`document.querySelector('.user-list')`);
  await click(".btn.user", userId);
  await waitFor(`document.querySelector('.composer')`);
}

/** Asks, then waits for `done` (selectors) to match something that wasn't on screen before: the thread keeps earlier turns. */
async function askQuestion(q, done = "#answer-heading, .card.error") {
  const fresh = JSON.stringify(done.split(",").map((s) => `${s.trim()}:not([data-before])`).join(", "));
  await evaluate(`(() => { for (const el of document.querySelectorAll(${JSON.stringify(done)})) el.setAttribute('data-before', '');
    const t = document.getElementById('question'); t.value = ${JSON.stringify(q)};
    t.dispatchEvent(new Event('input', { bubbles: true })); t.form.requestSubmit(); })()`);
  await waitFor(`document.querySelector(${fresh})`);
}

await send("Page.enable");
await send("Runtime.enable");
await send("Log.enable");
await viewport();
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: THEME }] });

/**
 * SC-004 (success criterion: first screen within 2 s on a slow connection): cold cache, Slow 4G,
 * time from navigation start until the sign-in list is on screen. Also the gzip size of every
 * script and stylesheet the first screen loaded (fails over 170 KB).
 */
async function firstLoad() {
  await send("Network.enable");
  await send("Network.setCacheDisabled", { cacheDisabled: true });
  await send("Network.emulateNetworkConditions", SLOW_4G);
  const { identifier } = await send("Page.addScriptToEvaluateOnNewDocument", { source: `
    new MutationObserver((_, obs) => {
      if (document.querySelector('.user-list')) { window.__firstScreenMs = performance.now(); obs.disconnect(); }
    }).observe(document, { childList: true, subtree: true });` });
  await send("Page.navigate", { url: `${BASE}/` });
  await waitFor("window.__firstScreenMs", 20000).catch(async (err) => {
    throw new Error(`${err.message} (page: ${await evaluate("location.href + ' ' + document.readyState + ' user-list=' + !!document.querySelector('.user-list')")})`);
  });
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

  console.log("answer (q04 casing torque with conflict), u01 pump technician");
  await signInAs("u01");
  await shot("02-ask-empty", { full: false });
  await askQuestion("Casing bolt torque for FRS-P-0031 after a seal change");
  await shot("03-answer-q04-conflict");

  console.log("source viewer for the bulletin (with placeholder page image)");
  await click("a.chip", "1");
  await waitFor(`document.getElementById('source-title')`);
  await shot("04-source-bulletin");
  await evaluate("history.back()");
  await waitFor(`document.getElementById('answer-heading')`);

  console.log("unverified (HCP-200 scan)");
  await askQuestion("Rated head of the HCP-200");
  await shot("05-unverified");
  await click("a.unverified", "value unverified", CUR);
  await waitFor(`document.getElementById('source-title') && document.querySelector('.page-image img')?.complete`);
  await shot("06-source-scan-translated-with-marker");

  console.log("source with page but no image (superseded) and not-visible");
  await go("#/sources/p_01d8fc970b80aa01db626b23");
  await waitFor(`document.getElementById('source-title')`);
  if (await evaluate("Boolean(document.querySelector('.page-image'))")) problems.push("superseded source rendered a page image");
  await shot("07-source-superseded-no-image");
  await go("#/sources/p_0ee8e5f1561408d13db4a416");
  await waitFor(`document.getElementById('nv-title')`);
  await shot("08-source-not-visible", { full: false });

  console.log("steps, possibly stale, undecided conflict (mock oil answer)");
  await go("#/ask");
  await askQuestion("Which oil for the VRS-75 RTM-C-0121?");
  await shot("09-answer-steps-stale-undecided-conflict");

  console.log("restricted, abstain, clarify as u03 (no high-voltage certification)");
  await signInAs("u03");
  await askQuestion("E-31 on TAC-C-0143, how do I reset it?");
  await shot("10-restricted");
  if (!(await evaluate(`${CUR}.querySelector('.missing-groups').innerText`)).includes("High-voltage electrical certification (VFD cabinets)")) {
    problems.push("restricted card does not use the /api/groups description");
  }
  await askQuestion("Warranty on the BX-20 conveyor");
  await shot("11-abstain");
  await askQuestion("Casing torque on the HCP-350 at Fresno");
  await shot("12-clarify");
  await click(".btn.option", "FRS-P-0031", CUR);
  await waitFor(`${CUR}.querySelector('.asset-id')?.textContent.includes('FRS-P-0031')`);
  const resent = await evaluate(`${CUR}.querySelector('.asked').textContent`);
  if (!resent.includes("HCP-350 at Fresno")) problems.push(`clarify resend lost the question: ${resent}`);

  console.log("did you mean, follow-up, new question");
  const typo = "What's the impeller-to-casing clearance spec on an HCP-20?";
  await askQuestion(typo);
  await shot("20-did-you-mean");
  if (!(await evaluate(`${CUR}.querySelector('.clarify .hint').textContent`)).includes("isn't in the documents")) {
    problems.push("did-you-mean clarify uses the machine-pick hint");
  }
  await click(".btn.option", "HCP-200", CUR);
  await waitFor(`document.getElementById('answer-heading') && !${CUR}.querySelector('.clarify')`);
  if (!(await evaluate(`${CUR}.innerText`)).includes("0.38 - 0.50 mm")) problems.push("did-you-mean tap did not reach the clearance answer");
  if (!(await evaluate("Boolean(document.getElementById('new-question'))"))) problems.push("no New question control while an answer is on screen");
  await shot("21-did-you-mean-answer-follow-up-bar");
  await click("#new-question", "New question");
  await sleep(100);
  if (await evaluate("Boolean(document.getElementById('answer-heading') || document.querySelector('.follow-up'))")) problems.push("New question did not clear the answer");
  await shot("22-new-question-cleared", { full: false });
  await askQuestion(typo);
  await askQuestion("Oh, I meant HCP-200", ".answering");
  const answering = await evaluate(`${CUR}.querySelector('.answering').textContent`);
  if (!answering.includes("Answering: What's the impeller-to-casing clearance spec on an HCP-200?")) problems.push(`follow-up not shown as read: ${answering}`);
  await shot("23-follow-up-answering");

  console.log("draft from restricted, edit, request approval");
  await askQuestion("E-31 on TAC-C-0143, how do I reset it?");
  await click("button", "Draft a work order", CUR);
  await waitFor(`document.getElementById('wo-summary')`);
  await shot("13-draft-form-needs-approval");
  await evaluate(`(() => { const t = document.getElementById('wo-summary'); t.value = 'E-31 trip on TAC-C-0143, needs reset under HV-PROC-07'; t.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await click("button", "Request approval");
  await waitFor(`document.querySelector('.status-pending_approval')`);
  await shot("14-draft-pending-approval");
  const restrictedText = await evaluate("document.body.innerText");
  if (!restrictedText.includes("Kenji Watanabe (u08)")) problems.push("pending draft does not name the eligible approver");
  const draftHash = await evaluate("location.hash");

  console.log("draft from a suggestion with no machine: field error, then created");
  await go("#/ask");
  await askQuestion("How do I reset E-31 on a VRS-110?");
  await click("button", "Draft a work order", CUR);
  await waitFor(`document.getElementById('wo-asset')`);
  await shot("13b-draft-choose-machine");
  await evaluate(`(() => { const t = document.getElementById('wo-asset'); t.value = 'TAC-C-9999'; t.dispatchEvent(new Event('input', { bubbles: true })); t.form.requestSubmit(); })()`);
  await waitFor(`document.getElementById('wo-asset-error')`);
  await shot("13c-draft-unknown-machine");
  if (await evaluate("Boolean(document.querySelector('.card.error'))")) problems.push("unknown machine shown as a page error");
  if ((await evaluate("document.getElementById('wo-asset').value")) !== "TAC-C-9999") problems.push("typed machine lost after the error");
  await evaluate(`(() => { const t = document.getElementById('wo-asset'); t.value = 'tac-c-0142'; t.dispatchEvent(new Event('input', { bubbles: true })); t.form.requestSubmit(); })()`);
  await waitFor(`document.getElementById('wo-summary')`);
  if (!(await evaluate("document.querySelector('.draft-form').innerText")).includes("TAC-C-0142")) problems.push("created draft is not for TAC-C-0142");

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
  if (!(await evaluate("document.body.innerText")).includes("Note: Approved, Daniel Reyes is booked for Thursday")) {
    problems.push("approved draft does not show the decision note");
  }
  await click("button", "Submit to MaintPro");
  await waitFor(`document.querySelector(${CONFIRM})`);
  await click(CONFIRM_BUTTON, "Send to MaintPro");
  await waitFor(`document.querySelector('.status-submitted')`);

  console.log("draft with direct submit to Servio, confirmation dialog");
  await signInAs("u09");
  await askQuestion("Which oil for the VRS-75 RTM-C-0121?");
  await click("button", "Draft a work order", CUR);
  await waitFor(`document.getElementById('wo-summary')`);
  await click("button", "Submit to Servio");
  await waitFor(`document.querySelector(${CONFIRM})`);
  await shot("15-draft-confirm-servio", { full: false });
  await click(CONFIRM_BUTTON, "Send to Servio");
  await waitFor(`document.querySelector('.status-submitted')`);
  await shot("16-draft-submitted");

  console.log("pending (slow) and 503 (fail)");
  await go("#/ask");
  await waitFor(`document.getElementById('question')`);
  await askQuestion("slow torque FRS-P-0031", ".card.pending");
  const sent = await evaluate(`({ box: document.getElementById('question').value,
    bubble: (document.querySelector('.card.pending').closest('.turn') ?? document).querySelector('.asked')?.textContent ?? '',
    kept: sessionStorage.getItem('copilot.question') })`);
  if (sent.box !== "") problems.push(`composer not emptied on send: "${sent.box}"`);
  if (!sent.bubble.includes("slow torque FRS-P-0031")) problems.push(`pending turn does not show the question: "${sent.bubble}"`);
  if (sent.kept !== "slow torque FRS-P-0031") problems.push(`question not kept in sessionStorage while pending: "${sent.kept}"`);
  await sleep(6500);
  await shot("17-pending-slow", { full: false });
  await waitFor(`document.getElementById('answer-heading')`, 10000);
  await askQuestion("this will fail");
  await shot("18-error-503", { full: false });
  const kept = await evaluate("document.getElementById('question').value");
  if (kept !== "this will fail") problems.push(`question not kept after 503: "${kept}"`);

  console.log("cancel puts the question back, but never over text typed meanwhile");
  await askQuestion("slow cancel FRS-P-0031", ".card.pending");
  await click(".card.pending button", "Cancel");
  await waitFor(`!document.querySelector('.card.pending')`);
  await shot("24-cancel-question-back", { full: false });
  const back = await evaluate("document.getElementById('question').value");
  if (back !== "slow cancel FRS-P-0031") problems.push(`question not back in the composer after cancel: "${back}"`);
  await askQuestion("slow cancel FRS-P-0031", ".card.pending");
  await evaluate(`(() => { const t = document.getElementById('question'); t.value = 'typed while waiting';
    t.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await click(".card.pending button", "Cancel");
  await waitFor(`!document.querySelector('.card.pending')`);
  const mine = await evaluate("document.getElementById('question').value");
  if (mine !== "typed while waiting") problems.push(`text typed while pending was overwritten after cancel: "${mine}"`);

  console.log("expired session keeps the question");
  await evaluate("fetch('/api/session', {method: 'DELETE'})");
  await askQuestion("question typed before expiry", ".user-list");
  await shot("19-session-expired", { full: false });
  await click(".btn.user", "u03");
  await waitFor(`document.getElementById('question')`);
  const afterExpiry = await evaluate("document.getElementById('question').value");
  if (afterExpiry !== "question typed before expiry") problems.push(`question lost after expiry: "${afterExpiry}"`);

  const stored = await evaluate("JSON.stringify({local: Object.keys(localStorage), session: Object.keys(sessionStorage)})");
  console.log(`storage: ${stored}`);
  if (JSON.parse(stored).local.length) problems.push(`localStorage used: ${stored}`);
} catch (err) {
  problems.push(`run aborted: ${err.message}`);
} finally {
  ws.close();
  chrome.kill();
}

for (const e of consoleErrors) problems.push(`console error: ${e}`);
if (problems.length) {
  console.log(`\n${problems.length} problem(s):`);
  for (const p of problems) console.log(`  - ${p}`);
  process.exit(1);
}
console.log("\nall screens rendered at 375 px with no console errors, no overflow, no small or overlapping tap targets, text AA, no withheld values");
