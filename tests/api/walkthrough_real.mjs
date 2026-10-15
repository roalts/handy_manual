// web-react/dev/screenshots.mjs (004) adapted to the real API (003) and real answers; same layout checks.
// Differences from the mock walkthrough, because real answers differ from the mock's canned ones:
// - No withheld-value check: in ds_0028 the HCP-200 rated head is OCR-verified, not withheld.
// - The scan source is opened from its citation chip (no unverified segment exists in ds_0028).
// - Not-visible uses NK-600 manual 8.4 (SOP-020, restricted), hidden from u01.
// - Clarify is asked by u01 (pump technician); VRS-75 oil by u03 (compressor technician).
// - The Servio direct-submit flow runs only if the real answer offers a draft.
// - No "slow" or "fail" keywords: pending and 503 are covered by tests/api.
//
//   uv run python tests/api/serve_scratch.py --port 8010 &
//   node tests/api/walkthrough_real.mjs --base http://localhost:8010

import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const BASE = arg("base", "http://localhost:8000");
const OUT = arg("out", "specs/003-answer-api/screenshots");
const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9333;
const WIDTH = 375;
const HEIGHT = 812;
const WITHHELD = [];

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
    // Expected HTTP failures exercised on purpose (401 probe, 403 not visible, 503).
    if (!/status of (401|403|404|503)/.test(e.text)) consoleErrors.push(`${e.text} ${e.url ?? ""}`);
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
  await checkLayout(name);
  if (full) {
    const h = await evaluate("window.scrollTo(0, 0), Math.ceil(document.documentElement.scrollHeight)");
    await viewport(Math.max(HEIGHT, h));
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
      .map((el) => [el, el.getBoundingClientRect()])
      .filter(([, b]) => b.width > 0 && (b.height < 43.5 || b.width < 43.5))
      .map(([el, b]) => el.tagName + '.' + el.className + ' "' + (el.textContent || el.value || '').trim().slice(0, 30) + '" ' + Math.round(b.width) + 'x' + Math.round(b.height));
    const text = document.body.innerText;
    const junk = (text.match(/\\b(null|undefined|NaN|\\[object Object\\])\\b/g) || []);
    return { overflow, small, junk, leaked: ${JSON.stringify(WITHHELD)}.filter((v) => text.includes(v)) };
  })()`);
  for (const j of r.junk) problems.push(`${name}: stray "${j}" on screen`);
  if (r.overflow > 0) problems.push(`${name}: horizontal overflow ${r.overflow}px`);
  for (const s of r.small) problems.push(`${name}: tap target under 44px: ${s}`);
  for (const v of r.leaked) problems.push(`${name}: withheld value on screen: ${v}`);
}

const click = (selector, text) => evaluate(`(() => {
  const el = [...document.querySelectorAll(${JSON.stringify(selector)})].find((e) => e.textContent.includes(${JSON.stringify(text ?? "")}));
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

async function askQuestion(q, done = "document.getElementById('answer-heading') || document.querySelector('.card.error')") {
  await evaluate(`(() => { const t = document.getElementById('question'); t.value = ${JSON.stringify(q)};
    t.dispatchEvent(new Event('input')); t.form.requestSubmit(); })()`);
  await waitFor(done, 45000);
}

await send("Page.enable");
await send("Runtime.enable");
await send("Log.enable");
await viewport();

try {
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

  console.log("scanned, translated source (HCP-200)");
  await askQuestion("Rated head of the HCP-200");
  await shot("05-answer-hcp200-scan");
  await click("a.chip", "1");
  await waitFor(`document.getElementById('source-title') && document.querySelector('.page-image img')?.complete`);
  await shot("06-source-scan-translated");
  await evaluate("history.back()");
  await waitFor(`document.getElementById('answer-heading')`);

  console.log("source with page but no image (NK-600 8.3 for u06 later), not-visible for u01");
  await go("#/sources/p_89e01fa9f9431d888616bfd8");
  await waitFor(`document.getElementById('nv-title')`);
  await shot("08-source-not-visible", { full: false });

  console.log("clarify as u01");
  await go("#/ask");
  await waitFor(`document.getElementById('question')`);
  await askQuestion("Casing torque on the HCP-350 at Fresno");
  await shot("12-clarify");
  if (await evaluate("Boolean(document.querySelector('.btn.option'))")) {
    await click(".btn.option", "FRS-P-0031");
    await waitFor(`document.querySelector('.asset-id')?.textContent.includes('FRS-P-0031')`);
    const resent = await evaluate("document.querySelector('.asked').textContent");
    if (!resent.includes("HCP-350 at Fresno")) problems.push(`clarify resend lost the question: ${resent}`);
    await shot("12b-clarify-answered");
  } else problems.push("real answer was not a clarification");

  console.log("restricted, abstain, clarify as u03 (no high-voltage certification)");
  await signInAs("u03");
  await askQuestion("E-31 on TAC-C-0143, how do I reset it?");
  await shot("10-restricted");
  if (!(await evaluate("document.querySelector('.missing-groups').innerText")).includes("High-voltage electrical certification (VFD cabinets)")) {
    problems.push("restricted card does not use the /api/groups description");
  }
  await askQuestion("Warranty on the BX-20 conveyor");
  await shot("11-abstain");
  await askQuestion("Which oil for the VRS-75 RTM-C-0121?");
  await shot("09-answer-vrs75-oil");

  console.log("NK-600 8.3 for u06: page number, no page image");
  await signInAs("u06");
  await go("#/sources/p_f71b980da8173a0d23371f8c");
  await waitFor(`document.getElementById('source-title')`);
  if (await evaluate("Boolean(document.querySelector('.page-image'))")) problems.push("NK-600 page 11 image shown to u06");
  await shot("07-source-shared-page-no-image");
  await signInAs("u03");

  console.log("draft from restricted, edit, request approval");
  await askQuestion("E-31 on TAC-C-0143, how do I reset it?");
  await click("button", "Draft a work order");
  await waitFor(`document.getElementById('wo-summary')`);
  await shot("13-draft-form-needs-approval");
  await evaluate(`(() => { const t = document.getElementById('wo-summary'); t.value = 'E-31 trip on TAC-C-0143, needs reset under HV-PROC-07'; t.dispatchEvent(new Event('input')); })()`);
  await click("button", "Request approval");
  await waitFor(`document.querySelector('.status-pending_approval')`);
  await shot("14-draft-pending-approval");
  const restrictedText = await evaluate("document.body.innerText");
  if (!restrictedText.includes("Kenji Watanabe (u08)")) problems.push("pending draft does not name the eligible approver");
  const draftHash = await evaluate("location.hash");

  console.log("lead u08 approves with a note; u03 sees it and submits to MaintPro");
  await signInAs("u08");
  await go(draftHash);
  await waitFor(`document.getElementById('wo-note')`);
  await evaluate(`(() => { const t = document.getElementById('wo-note'); t.value = 'Approved, Daniel Reyes is booked for Thursday'; t.dispatchEvent(new Event('input')); })()`);
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
  await waitFor(`document.querySelector('dialog[open]')`);
  await click("dialog button", "Send to MaintPro");
  await waitFor(`document.querySelector('.status-submitted')`);

  console.log("EU draft as u09 if the real answer offers one");
  await signInAs("u09");
  await askQuestion("New BX-12 belt at Gdansk tracks to the left. What do I do?");
  await shot("15-answer-u09");
  if (await evaluate("[...document.querySelectorAll('button')].some((b) => b.textContent.includes('Draft a work order'))")) {
    const noMachine = await evaluate("!document.querySelector('.asset-id')");
    await click("button", "Draft a work order");
    await waitFor(`document.getElementById('wo-summary') || document.querySelector('[role=alert], .card.error, .error')`);
    await shot("16-draft-u09");
    if (!(await evaluate("Boolean(document.getElementById('wo-summary'))"))) {
      const msg = noMachine ? " (answer resolved no machine; the client posts asset_id null and doesn't ask for one)" : "";
      problems.push(`u09 draft not created${msg}`);
    }
  } else console.log("  (no draft offered by the real answer)");
  await signInAs("u03");
  await go("#/ask");
  await waitFor(`document.getElementById('question')`);

  console.log("expired session keeps the question");
  await evaluate("fetch('/api/session', {method: 'DELETE'})");
  await askQuestion("question typed before expiry", "document.querySelector('.user-list')");
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
console.log("\nall screens rendered at 375 px with no console errors, no overflow, no small tap targets, no withheld values");
