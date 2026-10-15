# Web client (004) — web client agent

**State**: done (T022, the real-API walkthrough, is done; T047, the cutover task, still waits for the user)
**Current task**: none; see the 2026-10-14 18:05 entry
**Last updated**: 2026-10-14 18:05

## 2026-10-12 19:38 — Started, reading orchestrator.md

STATUS (to: orchestrator)

Read `orchestrator.md` up to "2026-10-12 19:36 — For the web client". Acknowledged: a source view
with a page number and `page_image_url: null` must render as text only with no error. The mock
covers that case with p_01d8fc970b80aa01db626b23 (VRS-75 service manual Rev B, page 3, signal
words; superseded), served with `page: 3` and `page_image_url: null`.

Done so far:
- `web/dev/fixtures/sources.json`: source views for every passage cited in the five examples,
  read once from ds_0026 (dataset version 26), plus one superseded and one possibly-stale passage.
  In the p_7a891cda95ff12c33c8caaa5 (HCP-200 1998 scanned manual, technical data page 3) fixture
  the rated-head value is replaced by `[[unverified:r_0000000000000000|page=3]]` so the viewer's
  marker path is exercised and the value never appears in the mock.
- `web/dev/fixtures/mock_oil.json`: one mock-only answer (validated with
  `AnswerResponse.check()`) covering what the five examples don't: numbered steps, superseded and
  possibly-stale citations, a conflict with `preferred: null`, an EU (Europe) asset so drafts
  target Servio, and a citation that answers 403 when opened.
- `web/dev/mock_api.py`: drafted, not yet run.

Next: client in `web/`, then tests, screenshots, plan.md and tasks.md.

## 2026-10-12 20:25 — Final report: client and mock built, verified at 375 px

STATUS (to: orchestrator)

All four user stories are built against the mock and pass a headless 375 px walkthrough with no
console errors. Re-read `orchestrator.md` and `answer-engine.md` before finishing; nothing there
changes my contracts. Following the HV-PROC-07 (VRS-110 drive fault reset procedure, restricted)
row in ds_0027 (dataset version 27), the mock's restricted response now lists whichever of cert-hv
(high-voltage certification) and family-compressors (Vastra VRS compressor training) the user lacks.

### Built, per user story

| Story | State | Notes |
|---|---|---|
| US1 (user story: ask and read on a phone) | done | All four statuses; machine header with bulletins; numbered steps; warnings; citation chips per sentence; notices; restricted card; abstain card distinct from errors; clarify resends with `asset_id` + `clarification_of`. Pending state, cancel, retry, kept question, 503 / no-connection / expired-session messages. |
| US2 (user story: check the source) | done | Viewer with title, revision, issue date, locator, superseded / possibly stale / scanned / machine-translated labels, original and English, page image only when `page_image_url` is set, "Not visible to you" on 403. Unverified segments and `[[unverified:…]]` markers show only "value unverified, see scanned page N" with a link to the page image. |
| US3 (user story: conflicts and notices) | done | Both sides always shown; preferred side marked "Applies to this machine" with the reason; `preferred: null` marks no side and says to check with a lead. |
| US4 (user story: draft a work order) | done | Prefilled draft; edit; who must approve and why; Request approval replaces Submit when needed; approve/reject for leads; confirmation dialog naming MaintPro or Servio; `Idempotency-Key` from the draft. |

Open tasks in `specs/004-mobile-web-client/tasks.md`: T022 (task: rerun the walkthrough against the
real 003 API) and T023 (task: hide the test-user sign-in list in production), both waiting on 003.

### Files

- Client: `web/index.html`, `web/styles.css`, `web/js/{app,api,answer,source,workorder,text,dom}.js`
- Tests: `web/tests/text.test.mjs`, `web/dev/test_mock_api.py`, `web/dev/screenshots.mjs`
- Mock: `web/dev/mock_api.py`, `web/dev/fixtures/{sources,mock_oil}.json`
- Docs: `specs/004-mobile-web-client/{plan,tasks}.md`, `specs/004-mobile-web-client/screenshots/` (19 PNGs)

### How to run

```bash
uv run python web/dev/mock_api.py      # then open http://localhost:8000/
node --test web/tests/*.test.mjs       # 9 tests, pure helpers
uv run python -m unittest web/dev/test_mock_api.py   # 8 tests, mock over HTTP
node web/dev/screenshots.mjs           # with the mock running; needs Google Chrome
```

Mock keywords are listed in plan.md, section "Running". The mock is stopped now; port 8000 is free.

### Verification

- The in-IDE browser tool would not open a tab for me ("No browser tab available" on every
  navigate). Instead, `web/dev/screenshots.mjs` drives headless Chrome over the DevTools protocol
  with no npm packages. It walks 19 screens at 375 px and fails on console errors, horizontal
  overflow, any tap target under 44 px, stray `null` / `undefined` text, or the withheld HCP-200
  rated-head value appearing anywhere on screen. It also checks that the question survives a 503
  and an expired session, that a clarify pick resends the original question, and that nothing is
  written to localStorage. Result: all pass.
- Screenshots in `specs/004-mobile-web-client/screenshots/`: 01-sign-in, 03-answer-q04-conflict
  (q04: casing torque for FRS-P-0031, the Fresno HCP-350 pump), 05-unverified,
  06-source-scan-translated-with-marker, 07-source-superseded-no-image, 08-source-not-visible,
  09-answer-steps-stale-undecided-conflict, 10-restricted, 11-abstain, 12-clarify,
  13-draft-form-needs-approval, 14-draft-pending-approval, 15-draft-confirm-servio,
  16-draft-submitted, 17-pending-slow, 18-error-503, 19-session-expired, plus 02 and 04.
- Spend: US$0. No model calls; `.env` not read.

### REQUEST (to: orchestrator): proposed contract changes

None of these block the client; each has a workaround in place.

1. **Dev user list endpoint** (http-api.md). The sign-in screen needs the test users, and no
   endpoint lists them. Proposed: `GET /api/dev/users` → `{"users": [{"user_id", "name", "title",
   "groups"}], "groups": {id: description}}`, development mode only, `404` when
   `APP_ENV=production`. The mock implements exactly this. Without it the client falls back to a
   user ID text field.
2. **Group descriptions** (http-api.md or answer.md). "Missing groups in plain words" needs the
   `users.json` descriptions; the client carries its own copy (`GROUP_WORDS` in `web/js/text.js`).
   Proposed: include them in the dev users response above, or in `Identity`, or as
   `restricted.missing_group_labels`.
3. **`viewer_url` is a client route** (answer.md). `/sources/{id}` is not under `/api`, so it
   isn't clear whether it's a page or an API path. The client treats it as a client route and
   links to `#/sources/{id}`. Proposed: say so in answer.md.
4. **Who approves** (work-orders-audit.md). WorkOrderDraft has no approver field, so the client
   derives "a field team lead for North America / Europe" from `target_system`. Proposed: add
   `approver_role` or `eligible_approvers` to the draft.
5. **Rejection note** (work-orders-audit.md). `approve` / `reject` take `{"note"}`, but the draft
   has no field to show it to the technician. Proposed: add `decision_note: str | None`.
6. **Editable fields** (http-api.md, PATCH). "Editable fields" isn't listed. The client sends
   `summary`, `work_steps`, `priority`, `fault_code` and `parts`; the mock rejects anything else
   with 422. Proposed: list these in the contract.
7. **Status codes for work-order state errors** (http-api.md). Not specified. The mock and client
   use `409 {"error": "invalid_state"}` (or `"not_editable"` on PATCH), and `422` for a missing
   `confirm` or `Idempotency-Key`. Proposed: write these down.
8. **Error body shape**. The client reads `{"error": code, "detail"?: string}` on every non-2xx
   response. Proposed: make that the general rule, and note that FastAPI's default 422 body
   (`{"detail": [...]}`) is handled too: the client only shows its own wording for 422.

### For the 003 (answer API) builder

- Serve `web/` at `/`: `index.html` for `/`, plus `/styles.css` and `/js/*.js` with
  `Content-Type: text/javascript` (ES modules fail with the wrong MIME type). Don't serve
  `web/dev/` or `web/tests/`. Optional: serve `index.html` for `/sources/*` and `/work-orders/*`;
  the client then rewrites those paths to its hash routes.
- Cookie: any name works. The client never reads the cookie; it only relies on same-origin
  `credentials: "same-origin"`. The mock uses `copilot_session` with `HttpOnly; SameSite=Lax;
  Path=/`. Use the same `SameSite=Lax`, so the `<img>` request for `page.png` carries the session.
- Send `Cache-Control: no-store` on every `/api` response, including `page.png` (FR-008: answers
  and sources must not be stored on the device).
- Headers the client sends: `Content-Type: application/json` and `Accept: application/json` on
  every call, plus `Idempotency-Key: <draft.idempotency_key>` on submit. The client reuses the
  key the server put in the draft and never generates its own.
- `401` on any endpoint takes the user to sign-in with the typed question kept; `403` on sources
  and drafts shows "Not visible to you"; `404` shows "not found".
- The client allows 60 s per request before showing "no answer arrived in time".
- The HCP-200 page-3 scan PNG is about 4 MB. On a phone connection a smaller rendition (JPEG or
  downscaled PNG) for `page.png` would help SC-004 (success criterion: first screen under 2 s on a
  slow connection) and general use.

## 2026-10-12 20:35 — Applied "Contract changes from the web client's eight requests"

STATUS (to: orchestrator)

Answers `orchestrator.md`, "2026-10-12 20:30 — Contract changes from the web client's eight
requests". All eight decisions are applied to the client and the mock, including the two that
differ from my proposal. No open questions.

### Mock (`web/dev/mock_api.py`)

- `GET /api/dev/users` now returns only `{"users": [...]}` (the group map was moved out).
- New `GET /api/groups` → `{group id: description}` from `users.json`; `401` without a session.
- Drafts carry `eligible_approvers` (user IDs; empty together with "no eligible approver") and
  `decision_note` (the `note` from approve or reject).
- Error codes match http-api.md "Errors": unknown sign-in user is now `422 invalid_request`
  (was `unknown_user`), a missing page image is `404 not_found` (was `no_page_image`), unsupported
  methods are `404 not_found` (was `405 method_not_allowed`).
- `web/dev/test_mock_api.py` now checks every error body against the code list and validates
  every returned draft with `copilot_contracts.work_orders.WorkOrderDraft` (when run under `uv`).
  New checks: `/api/groups`, `eligible_approvers` for u03 (technician without high-voltage
  certification; approver u08, NA team lead), an empty list for u08's own draft (no eligible
  approver) and for the Servio draft (no approval needed), `decision_note` after approval,
  `422` for a non-editable PATCH field, and `409 not_editable` after submit.

### Client (`web/`)

- Restricted card: missing groups now use the `/api/groups` descriptions, loaded once a session
  exists, for example "High-voltage electrical certification (VFD cabinets)" followed by
  "(cert-hv)". `GROUP_WORDS` stays only as the offline fallback. Since the descriptions are full
  phrases, the card now lists them under "Its steps are not shown because you don't have:"
  instead of putting them inside a sentence.
- Draft screen: "Can approve: Kenji Watanabe (u08)" from `eligible_approvers` (names from the dev
  user list, IDs when it's unavailable). Approve and Reject show only for users in that list, with
  an optional note field. Approved and rejected drafts show who decided and the `decision_note`.
  The client no longer works out approvers from groups.
- `viewer_url` handling and error handling needed no change; they already matched the decision.

### Verification

- `node --test web/tests/*.test.mjs`: 11 pass (new: server group words override the fallback;
  approver labels).
- `uv run python -m unittest web/dev/test_mock_api.py`: 8 pass with the stricter checks.
- `node web/dev/screenshots.mjs`: all screens pass at 375 px (no console errors, overflow, small
  tap targets, stray `null`, or withheld values). The run now covers the full approval round
  trip: u03 requests approval, u08 approves with a note, u03 sees the note and submits to
  MaintPro. New screenshots: `14b-draft-approver-view.png` and `14c-draft-approved-with-note.png`.
  `10-restricted.png` and `14-draft-pending-approval.png` were regenerated.
- Docs: `specs/004-mobile-web-client/plan.md` (design decisions) and `tasks.md` (T024–T028,
  tasks for this change, all done) are updated.
- Spend: US$0. No model calls; `.env` not read. The mock is stopped, so port 8000 is free.

Still open, waiting on 003: T022 (task: rerun the walkthrough against the real API) and T023
(task: hide the test-user sign-in list in production; the client already falls back to a user ID
field when `/api/dev/users` answers 404).

## 2026-10-12 22:55 — Drafts from a suggestion without a machine

STATUS (to: orchestrator)

Answers the REQUEST (to: web client) in `orchestrator.md`, "2026-10-12 22:45 — Review of the
answer API's final report". All three items are done. Before starting I re-read
`answer-api.md`, `work-orders.md` and the current contracts.

### What changed

1. **Machine field before the draft exists.** When `work_order_suggestion.asset_id` is null,
   "Draft a work order" opens a "New work order" screen (`#/work-orders/new`, in
   `mountNewDraft` in `web/js/workorder.js`). It explains that the answer didn't name one machine
   and asks for the asset ID (for example TAC-C-0142, a Tacoma VRS-110 compressor). It shows the
   suggested summary, fault code, certification, campaign and parts read-only. Nothing is created
   until "Create draft" is pressed, so a draft with no machine can never reach submit. Once
   created, the normal draft screen takes over (edit, request approval, submit with
   confirmation). Suggestions that already have a machine work as before.
2. **Top-level `asset_id`.** The client sends `{"answer_id", "suggestion", "asset_id"}`, with the
   ID trimmed and upper-cased, and only when the suggestion has no machine. Errors about the
   machine appear under the field: red border, `aria-invalid`, `role="alert"`, the typed value
   kept and focused. This applies to `404`, `403`, and any `422` whose detail names the asset.
   Anything else (no connection, other errors) is a form message. It's never a page error.
3. **Mock case and tests.** "E-31" (compressor drive fault) without a TAC-C asset ID in the
   question, for a user missing HV-PROC-07's groups, returns restricted with `asset: null` and
   `suggestion.asset_id: null` (validated with `AnswerResponse.check()`). The mock's
   `POST /api/work-orders` now takes top-level `asset_id` with the same rules as the real 005
   (work orders) service: required when the suggestion has none, must match when it has one,
   unknown fields are `422`.

### QUESTION (to: orchestrator): unknown machine is 422 in the real API, not 404

Your request says the API answers `404` or `403` for a machine that isn't found or isn't
visible. The real API (003 over 005) answers `422 invalid_request` with detail "unknown asset
TAC-C-9999". Machines have no visibility rule of their own: `403 not_visible` on create only
happens when a cited passage is hidden. I checked this against the real API at no cost (see
Verification). The mock now copies the real `422`. The client shows all three cases as a field
error, so nothing breaks whichever way http-api.md is written. Should the contract say
`422 invalid_request` for an unknown machine (what the API does today), or should 005 change to
`404 not_found`?

### Also aligned with the current contracts (found while doing this)

- 005's `needs_specialist` and `return_visit` (now in `WorkOrderDraft` and the PATCH list) are
  two checkboxes under "Also needed" on the draft form. The mock adds them to drafts and turns
  them into the "specialist" and "return visit" approval reasons.
- `503 submission_failed` on submit now reads "MaintPro/Servio couldn't be reached, so nothing
  was submitted. The draft is unchanged; submitting again is safe." (It reuses the same
  idempotency key.)

### Verification

- `uv run python -m unittest web/dev/test_mock_api.py`: 10 pass (new: draft needs a machine,
  covering missing, unknown, mismatch, unknown field and the created draft on MaintPro with u08
  as approver; specialist and return visit need approval). Every draft is still validated against
  `WorkOrderDraft` and every error body against the http-api.md code list.
- `node --test web/tests/*.test.mjs`: 13 pass (new: `assetFieldError` for 404, 403, asset 422,
  other 422, network and 503; `normalizeAssetId`).
- `node web/dev/screenshots.mjs --base http://localhost:8020`: all screens pass at 375 px. New
  steps: u03 (compressor technician without high-voltage certification) asks "How do I reset
  E-31 on a VRS-110?", taps "Draft a work order", enters TAC-C-9999 (field error, no page error,
  value kept), then tac-c-0142 (draft created for TAC-C-0142). New screenshots:
  `13b-draft-choose-machine.png` and `13c-draft-unknown-machine.png`. `13-draft-form-needs-approval.png`
  now shows the two checkboxes. I ran the mock on port 8020 so port 8000 stays free for the real
  API. It's stopped now.
- **Real API, create endpoint only (no model calls):** I ran `tests/api/serve_scratch.py` on port
  8030, which keeps drafts and audit in a temporary schema that is removed on exit, with a
  temporary outbox. As u03 I posted the restricted example's suggestion with `asset_id: null`:
  - with no machine: `422` "asset_id is required: choose the machine for this work order"
  - with TAC-C-9999: `422` "unknown asset TAC-C-9999"
  - with TAC-C-0142: `201`, MaintPro, approval reason "certification", eligible approver u08
  - with a suggestion for TAC-C-0143 plus TAC-C-0142: `422` "the suggestion is for TAC-C-0143,
    not TAC-C-0142"

  The client maps each of these as described. On exit: no outbox files, and the audit rows were
  in the scratch schema only. I didn't run the full client walkthrough against the real API,
  because its answers need model calls and this task's budget is US$0.
- Spend: US$0. I made no `/api/ask` calls. `.env` was read only by the server process; I didn't
  open it.

### Files changed

`web/js/{app,text,workorder}.js`, `web/styles.css`, `web/dev/{mock_api,test_mock_api}.py`,
`web/dev/screenshots.mjs`, `web/tests/text.test.mjs`,
`specs/004-mobile-web-client/{plan,tasks}.md` (T029–T032, tasks for this request, all done),
and the screenshots listed above.

Still open: T022 (task: rerun the full walkthrough against the real API; needs a small model
budget) and T023 (task: hide the test-user sign-in list in production; the client already
falls back to a user ID field when `/api/dev/users` answers 404).

## 2026-10-12 23:40 — Follow-ups and "did you mean" done in client and mock

STATUS (to: orchestrator)

Answers "2026-10-12 23:25 — Follow-ups and "did you mean" (user decision, contract change)",
REQUEST (to: web client). All four points are done. No model calls, US$0.

1. **`previous`.** While an answer is on screen, the next message carries `previous` =
   `{answer_id, question_used or the asked text, asset.asset_id}`. A "Follow-up to the answer
   above · New question" bar sits above the composer, and the placeholder reads "Ask a
   follow-up". "New question" clears the answer and `previous`. Sign-out and reload clear them
   too, because answers are kept in memory only (`sessionStorage` still holds only the
   unsent question text).
2. **"Answering: …"** is shown under "You asked" when `question_used` is set and differs from the
   typed text.
3. **Clarify options.** An option with `question` resends that text as a new ask. An option with
   `asset_id` resends the question (`question_used` if set) with `asset_id` and
   `clarification_of`. Both keep the clarify's own `previous`. When every option is a `question`,
   the hint reads "That name isn't in the documents. Tap the right one to ask again:" instead of
   "The answer depends on the machine."
4. **Mock and tests.**
   - Mock: `previous` is validated (422 on a bad shape or unknown keys).
   - Mock: follow-up phrasings ("oh", "and", "what about", "I meant"…) are rewritten against
     `previous.question`, and `question_used` is set.
   - Mock: `previous.asset_id` is carried over unless the follow-up names a machine. A follow-up
     naming a machine the canned answers don't cover gets "no canned answer", never the old
     machine.
   - Mock: "HCP-20" (one character off HCP-200, the Halden pump) returns "Did you mean
     HCP-200?". A model name with no close match returns an abstain saying the name isn't in the
     documents.
   - New fixture: the HCP-200 clearance answer (0.38 - 0.50 mm diametral, from the German scan).
   - Mock tests (14, all pass) cover: HCP-20 → did you mean → "Oh, I meant HCP-200" → the clearance
     answer with `question_used`; a new topic with `previous` (no `question_used`); a follow-up
     naming FRS-P-0012 (Fresno pump) switching machine; a follow-up to the E-31 (compressor fault
     code) answer still restricted for u03 (technician without high-voltage certification), with
     TAC-C-0143 (compressor asset ID) carried; an invalid `previous` → 422.
   - Every ask body in the mock tests is checked against `AskRequest` (blank questions must also be
     422), and responses against `AnswerResponse.check()`.
   - Node tests (15, all pass) add `previousTurn` and `clarifyRequest`.
   - Walkthrough (`node web/dev/screenshots.mjs --base http://localhost:8020`): every screen passes
     at 375 px. New screens: `20-did-you-mean`, `21-did-you-mean-answer-follow-up-bar`,
     `22-new-question-cleared`, `23-follow-up-answering`.

Docs: plan.md "Design decisions" and "Running" (mock keywords); tasks.md Phase 11, T048–T052
(tasks: mock follow-ups, mock did-you-mean, client follow-ups, abstain notice title, tests), all
done.

Noticed: someone added "Migration to React" to plan.md, and T033–T047 (tasks: React rebuild
and cutover) to tasks.md. I added my tasks after those, without renumbering, and noted under
Phase 11 that the React client must pass the same new walkthrough checks. If the React work is
starting, its agent should pick up `previousTurn` and `clarifyRequest` from `web/js/text.js`.
Also, `web/index.html` and `web/js/app.js` were renamed to "Handy Manual" at 23:20, with Enter
now sending. I kept both changes.

## 2026-10-12 23:40 — Abstain notices are always labelled "not visible"

REQUEST (to: orchestrator, for the answer engine)

`_abstain` in `src/copilot_answer/engine.py` gives every abstain notice the kind `not_visible`.
That includes `unknown_asset` ("No machine with the ID … is in the fleet records.") and the new
"name isn't in the documents" case. Clients title `not_visible` notices "Not visible to you".
That is the hidden-content wording the 23:25 decision rules out for names that don't exist.

The client now guards against this. On an abstain whose `abstain_reason` isn't `not_visible`, a
`not_visible` notice is titled "Why there's no answer". `no_permitted_source` now reads "Your
sources don't cover this." (screenshot `11-abstain`).

Proposal: the engine uses `not_visible` only for `abstain_reason: not_visible`, and adds a notice
kind such as `no_answer` for the other reasons. That needs a contract change to the notice kinds in
answer.md, so it is your decision. The client guard can stay either way.

Still open: T022 (task: rerun the full walkthrough against the real API; needs a small model
budget, and now also the engine's follow-up rewrite) and T023 (task: hide the test-user sign-in
list in production).

## 2026-10-12 23:54 — `no_answer` notice done; mock serves a built client

STATUS (to: orchestrator)

Answers "2026-10-12 23:50 — Review of the API and web client follow-up reports" (REQUEST to web
client) and the npm-free part of "2026-10-12 23:55 — Brief: React client (004 Phase 10, user
decision)".

- **`no_answer`** (T053, task: new notice kind): the plain client titles it "Why there's no
  answer" and styles it like `not_visible`. The guard stays: a `not_visible` notice on an
  abstain whose reason isn't `not_visible` gets the same title. The mock now emits `no_answer`
  for every abstain except `not_visible`, as the engine will.
- **T036** (task: `--web DIR` for the mock): `uv run python web/dev/mock_api.py --web
  web-react/dist` serves a built client. `/assets/*` files get the right `Content-Type`, and
  `index.html` is served for `/`, `/sources/*` and `/work-orders/*`. Nothing outside the
  directory is served, and neither is its `dev/` or `tests/`. That last rule is now enforced
  for `web/tests/` too, which was served before. The default is still `web/`.
- **T046** (task: static-files contract change): marked done per your 23:55 decision.
- Tests: mock 15 pass, including the new `test_serves_another_web_dir`. Node 16 pass. The
  walkthrough passes on every screen at 375 px.

Contract example, not mine to edit: `specs/contracts/examples/abstain.json` (BX-20 warranty,
`no_permitted_source`) still has a `not_visible` notice, which breaks the new rule. The mock
relabels it when serving.

## 2026-10-12 23:54 — npm registry rejects the saved credentials

BLOCKER (to: orchestrator, for the user)

T033–T035 (tasks: React project, Tailwind and shadcn/ui, AI Elements) need npm packages. On this
machine npm is set up for the internal registry `unpm.uberinternal.com` (user-level `~/.npmrc`
from the uber-developer Homebrew package, `always-auth = true`). Every request there returns
`401 Incorrect or missing password`, including `npm view react version`. I have not touched
credentials, and I have not tried another registry. Bypassing the company's configured mirror is
the user's decision, not mine.

The user can unblock this in one of two ways:
1. Refresh the internal registry login (whatever the uber-developer setup uses, e.g. re-running
   its npm auth step or `npm login --registry https://unpm.uberinternal.com`). Then tell me to
   continue. The lockfile will then point at the internal mirror.
2. Allow the public registry for this project only. I would add `web-react/.npmrc` with
   `registry=https://registry.npmjs.org/` and leave the user-level config alone.
   `package-lock.json` would then record public-registry URLs.

Until then I'm not writing React code I can't install, type-check or build. Untested code would
only have to be redone. Nothing else in the brief is waiting on this, and the plain client stays
in service.

## 2026-10-13 00:28 — React client built (T033–T045), stopped before cutover

STATUS (to: orchestrator)

Answers "2026-10-12 23:55 — Brief: React client (004 Phase 10, user decision)" and "2026-10-13
00:10 — npm registry (user decision)". I read the answer engine's 23:58 report and your 00:05
review. Neither changes anything for the client. I wrote no separate progress STATUS after T039
(task: app shell, router and query client). T033–T039 landed in one pass, and none of it could
be checked until the whole app built, so this entry covers both. I stopped before T047 (task:
cutover). The plain client in `web/` is unchanged and still the default.

**Result.** The walkthrough passes against the React build, with every check:

- all 27 screens at 375 px;
- no console errors, no horizontal overflow, no tap targets under 44 px, no stray `null`;
- the withheld HCP-200 (1998 pump manual, German scan) rated-head value never on screen;
- only `copilot.question` in `sessionStorage`, nothing in `localStorage`.

The two new checks pass too:

| Check | Limit | React build | Plain client |
|---|---|---|---|
| First screen on Slow 4G, cold cache | 2,000 ms | 1,877 ms (same in 3 runs) | 3,055 ms |
| First-load JS and CSS, gzip | 170 kB | 126.1 kB in 6 files | 23.6 kB in 8 files |

The plain client now fails the timing check: its 8 ES modules load as a chain of requests, each
waiting 562.5 ms on Slow 4G. Until the cutover, the walkthrough on `web/` reports that as its one
problem. Every other check passes on both clients.

To reproduce:

```
cd web-react && npx -y npm@11 ci --ignore-scripts && npm run build && cd ..
uv run python web/dev/mock_api.py --port 8020 --web web-react/dist &
node web/dev/screenshots.mjs --base http://localhost:8020 --out /tmp/shots-react
```

The React screenshots are in `specs/004-mobile-web-client/screenshots-react/`. The plain set in
`screenshots/` is left alone until T047 (task: cutover) regenerates it.

**Other checks:**

- `npm run build`, which type-checks first: clean.
- `npm run lint`: clean. `react/no-danger` is an error, `innerHTML` and `outerHTML` are
  restricted, and importing `streamdown` is banned.
- `npm test`: 18 Vitest tests pass. That is every case of `web/tests/text.test.mjs`, plus
  `no_answer` (the notice kind for abstains other than not-visible) and `isDidYouMean`.
- The 7 contract examples are type-checked against the generated `src/lib/contract.ts`: the 5 in
  `specs/contracts/examples/` and the 2 mock fixtures.
- Mock tests: 16 pass (`uv run python -m unittest web/dev/test_mock_api.py`).
- Plain client node tests: 16 pass.

**What the React client covers** (T040–T044, tasks: ask screen, answer, source sheet, conflict,
draft sheet), including everything the plain client gained after the plan was written:

- follow-ups: `previous`, the follow-up bar, "New question", and "Answering: …" when
  `question_used` differs;
- "did you mean" options that resend their `question`, and machine options that resend
  `asset_id` and `clarification_of`;
- the machine field for drafts without a machine (T030, task: ask for the asset ID first), with
  the field error kept beside the typed value;
- the `no_answer` notice, titled "Why there's no answer", with the guard for `not_visible`
  notices on other abstains;
- the `needs_specialist` and `return_visit` checkboxes.

The source and draft open as bottom sheets with their own hash routes. Pinch-zoom on page images
is lazy-loaded. The submit confirmation is an accessible alert dialog naming MaintPro or Servio,
and the submit sends an `Idempotency-Key`.

**Walkthrough changes in `web/dev/screenshots.mjs`.** Beyond selectors there are two, and both
still pass on the plain client:

1. The confirmation is found as `dialog[open], [role=alertdialog]`. Its buttons are found as
   `dialog[open] button, [role=alertdialog] button`.
2. Synthetic `input` events are created with `bubbles: true`, as real typing does. React listens
   at the document root, so a non-bubbling event never reached it.

Added, per the brief: the Slow 4G first-screen timing and the gzip size check, which run first.
Slow 4G here is the Chrome DevTools preset: 562.5 ms latency, 1.44 Mbit/s down, 675 kbit/s up.
The timing runs from navigation start until `.user-list` (the sign-in user list) is on screen.

**Mock change** (`web/dev/mock_api.py`): static `.html`, `.js`, `.css`, `.svg` and `.json` files
are gzipped when the request's `Accept-Encoding` allows it, with `Vary: Accept-Encoding`. Without
this the timing would measure uncompressed transfer, which no real server does. A new test,
`test_static_gzip_when_accepted`, covers it.

**What it took to reach 2 s.** The first build took 2,502 ms. Two changes brought it down:

- A 6-line inline script in `web-react/index.html` starts `/api/session` and `/api/dev/users`
  while the bundle downloads. `api()` uses each early response once and falls back to a normal
  request if it failed.
- Sonner (toasts) loads after the first screen.

A Content-Security-Policy added later would need the inline script's hash. Nothing in
`specs/contracts/` sets one today.

**Packages**, all pinned exactly. `package-lock.json` is written, but the workspace isn't a git
repository, so nothing is committed. `web-react/.gitignore` covers `node_modules/`, `dist/` and
`*.tsbuildinfo`.

- Runtime: @hookform/resolvers 5.9.1, @tanstack/react-query 5.104.2,
  class-variance-authority 0.7.1, clsx 2.1.1, lucide-react 1.56.0, radix-ui 1.8.1, react 19.3.0,
  react-dom 19.3.0, react-hook-form 7.90.0, react-zoom-pan-pinch 4.2.0, sonner 2.0.8,
  tailwind-merge 3.7.0, vaul 1.1.2, zod 4.6.7.
- Development: @eslint/js 9.39.5, @tailwindcss/vite 4.3.3, @types/node 26.6.5, @types/react
  19.3.0, @types/react-dom 19.3.0, @vitejs/plugin-react 6.1.2, eslint 9.39.5, eslint-plugin-react
  7.37.5, eslint-plugin-react-hooks 7.1.1, globals 17.13.0, json-schema-to-typescript 16.0.0,
  tailwindcss 4.3.3, tw-animate-css 1.4.0, typescript 6.0.3, typescript-eslint 8.71.2, vite 8.3.4,
  vitest 5.0.4.

**Registry and install scripts:**

- `web-react/.npmrc` holds only `registry=https://registry.npmjs.org/`. I didn't touch
  `~/.npmrc` or any credentials, and no token is in the project.
- All 459 `resolved` URLs in the lockfile are on `https://registry.npmjs.org`.
- Every install ran with `--ignore-scripts`. Only one package has an install script: `fsevents`
  2.3.3, an optional macOS file watcher pulled in by Vite. It ships a prebuilt binary and works
  without the script, so the script was never run. No other install scripts were allowed.

**Deviations from the plan:**

- npm 11 is needed: `npx -y npm@11 ci --ignore-scripts`. This machine's npm 10.9.2 crashes in
  `npm install` while resolving Vitest's peer dependencies ("Cannot read properties of null
  (reading 'edgesOut')"). The global npm is unchanged.
- ESLint 9.39.5, not 10: `eslint-plugin-react` doesn't support 10 yet.
- TypeScript 6.0.3: typescript-eslint 8.71.2 supports TypeScript below 6.1.
- AI Elements are trimmed further than planned. Removed: Streamdown, `motion` (the shimmer is
  plain CSS), `use-stick-to-bottom` (an answer must be read from the top), hover cards and the
  `ai` package. Each file's header comment says what was removed.
- The shadcn CLI puts files into a literal `@/` folder and adds a wrong `cn` package to
  `package.json`. I moved the files and removed the package. Running the CLI again will repeat
  this.

Recorded in `specs/004-mobile-web-client/tasks.md` (T033–T045 checked) and `plan.md` ("As built",
under "Migration to React").

REQUEST (to: answer API), per your 23:55 brief: T045 (task: walkthrough against the built
client) is done, so the `WEB_DIR=web-react/dist` tests can start. A suggestion, not a contract
change: gzip static files when `Accept-Encoding` allows, as the mock now does. On Slow 4G the
React bundle is 126 kB gzipped against about 420 kB uncompressed, so serving it uncompressed
would miss the 2 s first screen.

Still open from 23:54: `specs/contracts/examples/abstain.json` (contract example: BX-20 warranty,
`no_permitted_source`) has a `not_visible` notice where the 23:50 decision calls for
`no_answer`. That file isn't mine to edit, and the mock relabels it when serving.

**Next.** I'm waiting for your walkthrough check and the user's go-ahead before T047 (task:
cutover: `web-react/` becomes `web/`, and the plain client is deleted). Model spend this round:
US$0, no model calls.

## 2026-10-13 14:32 — UI overhaul step 1: three design directions ready

STATUS (to: orchestrator)

This answers step 1 of "2026-10-13 13:45 — Brief: UI overhaul of the React client (user
decision)". I read your 00:35 review and the answer API's 00:40 report; neither changes this
step. I did step 1 only and stopped. The shipping client in `web-react/` and the plain client in
`web/` are unchanged, and so is the mock.

**Where to look:** `specs/004-mobile-web-client/design/README.md`. It has one paragraph per
direction (palette, type scale, and how citations, warnings and conflicts look). Each direction
folder holds 10 screens and an `overview.png`, light row above dark:

| Direction | Feel | Citations |
|---|---|---|
| `graphite/` | minimal monochrome, one cobalt accent, almost no boxes | small superscript numbers, one per sentence |
| `copper/` | warm paper, a copper brand colour, soft rounded surfaces, the answer on one soft card | a source-name pill per sentence ("SB-2025-009 +1") |
| `console/` | dense pro tool, hairlines, monospace codes and capital labels, teal accent | `[1]` `[2]`, one per source |

**Screens.** Each is at 375 px, in light and dark, on mock API data captured from
`web/dev/mock_api.py`:

1. Empty state.
2. q04 (golden question: casing bolt torque on FRS-P-0031) with its bulletin, warning and
   conflict.
3. Restricted: E-31 (compressor fault code) on TAC-C-0143 (Tacoma VRS-110 compressor) for u03
   (technician without high-voltage certification), naming HV-PROC-07 (high-voltage repair
   procedure, restricted) and cert-hv (permission group: high-voltage certified).
4. The source panel for SB-2025-009 (Halden service bulletin).
5. A two-turn thread: "Did you mean HCP-200?" (HCP-200: Halden pump model), then the follow-up
   "Oh, I meant HCP-200" with "Answering: …".

The mock has no canned answer for "and on FRS-P-0012?", so the thread uses the did-you-mean flow,
which it does support.

**The brief's rules, in all three directions:**

- The answer text comes first.
- The machine, bulletins and notices are chips that expand in place, not stacked cards.
- Warnings and restricted procedures always have colour, an icon and a word.
- Conflicts show both sides, with the preferred side marked "Applies to this machine" and the
  reason. `preferred: null` marks neither side; the renderer supports it, but q04 doesn't use it.
- Unverified values would render only "value unverified, see scanned page N"; none of these
  screens has one.
- The identity is "Handy Manual" with an SVG mark (a hex nut with an H). System fonts only.

**Checks.** A new script, `node web/dev/mockups.mjs`, renders all 30 screens and checks each
one. All 30 pass:

- No horizontal overflow.
- Every control is at least 44 × 44 px, measured on its own box. The visible number or pill
  sits inside a 44 px box that doesn't widen the line, so the rectangle is the real tap area.
- No two controls overlap. This is a new check the walkthrough doesn't have yet. I'd add it in
  step 2. It is stricter, not looser.
- WCAG AA text contrast in both themes, placeholders included. The lowest ratios are 5.92:1 in
  Graphite, 5.33:1 in Copper and 4.92:1 in Console.
- No text under 14 px, and body text at 16 px or more.
- No console errors.

**For the pick:**

1. Graphite and Copper group a sentence's citations into one control. It's named for every
   source ("Sources 1: Halden SB-2025-009, p. 1, 1 Summary; 2: …"), and tapping it would open the
   source panel on the first source with a switcher. That is a behaviour change from one
   control per source. Console keeps one control per source, at the cost of a visible gap
   between neighbouring `[1]` `[2]`, since each needs its own 44 px box.
2. Copper's rounded titles use the system's rounded face (`ui-rounded`). iPhones have it; other
   phones fall back to the normal system font. No web font is loaded.
3. Size: the directions use CSS and inline SVG only and add no packages. I expect no
   measurable change to the 126 kB first load, but I'll measure in step 2.

**Not done, as this was step 1 only:** your 00:35 note that the mock can stop relabelling
`examples/abstain.json`'s notice. I'll do that with step 2.

Model spend: US$0, no model calls.

## 2026-10-13 15:10 — UI overhaul step 2: Graphite built into web-react/, all checks pass

STATUS (to: orchestrator)

Done: everything in "2026-10-13 14:50 — UI overhaul step 2". I stopped before T047 (task:
cutover).

**Result.** The React client in `web-react/` now uses Graphite in light and dark. The walkthrough
passes every check in both themes:

| | Light | Dark | Limit |
|---|---|---|---|
| First screen on Slow 4G, cold cache | 1,868 ms | 1,870 ms | 2,000 ms |
| First-load JS and CSS, gzip | 126.0 kB | 126.0 kB | 170 kB |

The 28 screens per theme are in `specs/004-mobile-web-client/screenshots-react/light/` and
`/dark/`, replacing the old flat set. `npm run build` is done, and http://localhost:8000 serves the
new build (assets `index-CF_aFC2j.js` and `index-GaOPvlAg.css`). I didn't restart that server.

**What changed, per request:**

1. **Every screen and state in Graphite:**
   - Sign-in.
   - The ask screen as a thread of turns: pending with the shimmer and the slow hint after 6 s,
     cancel, and 503, offline and expired session as one error block that keeps the question.
   - Clarify for machine and did-you-mean. Options in older turns are disabled.
   - Abstain with `no_answer` (notice kind: why there's no answer) and `not_visible` (notice
     kind: the source exists but isn't visible to this user).
   - Unverified values: only "value unverified, see scanned page N".
   - Superseded and possibly-stale labels, each with an icon and a word.
   - The page image with pinch-zoom.
   - The draft sheet: machine field, approval states with icons, approver view, confirmation
     naming MaintPro or Servio and the asset ID, and submitted.
   - "New question" in the header and above the composer.

   The 13:45 rules hold:
   - Answer text comes first; machine, bulletins and notices are compact expandable chips.
   - Conflicts show both sides, with "Applies to this machine" and the reason; `preferred: null`
     marks neither and says to check with a lead.
   - The thread is in memory only. Only the latest settled turn is sent as `previous`. Storage
     after the run: `localStorage` empty, `sessionStorage` holds only `copilot.question`.
2. **Source switcher.** A citation that holds several sources opens the sheet on the first one.
   Above it sits a "Sources cited together" row of numbered buttons:
   - Each is 44 px with the name "Source n: title, locator", and the current one has
     `aria-current`.
   - Left and Right arrow keys move between them.
   - Switching replaces the route, so Back still closes the sheet.
   - The change is announced from a live region inside the sheet, because the modal hides the
     rest of the page from screen readers.
   - The header line reads "Source n · document type".
   - The route `#/sources/{id}` on its own opens that one passage with no switcher.
3. **Walkthrough (`web/dev/screenshots.mjs`).**
   - New checks: the no-overlap check from `mockups.mjs`, plus its WCAG AA contrast check, so the
     contrast requirement is measured on the real app in both themes. Both run at full page
     height, so the sticky composer doesn't count as covering content.
   - With a dialog open, only the dialog is checked. A wrapped inline link is compared line by
     line, and a sticky bar isn't compared with the content scrolling under it. Disabled
     controls and the gradient shimmer text are skipped. The shimmer's highlight is now ink,
     not paper, so its text never drops below the secondary text colour.
   - `--theme light|dark` uses emulated `prefers-color-scheme`.
   - Selectors only: waits and clicks are scoped to the current turn, and each question waits
     for something that wasn't on screen before. Every check is kept.
   - The plain client still passes every check except the 2 s first screen (3,038 ms).
4. **Measured:** see the table above.
5. **Mock:** `answer_ask` no longer relabels abstain notices; `examples/abstain.json` carries
   `no_answer` itself. `uv run python -m unittest web/dev/test_mock_api.py`: 16 tests pass.

**Other checks:** `tsc -b`, `eslint .` and Vitest (18 tests) all pass.

**Two problems found and fixed during the run:**
- The confirmation dialog clipped its sentence to one line and hid the asset ID. shadcn's alert
  title clamps to one line, so I removed the clamp.
- The restricted card's "Draft a work order" button overlapped the citation above it by 1 px.

**Not covered by a screenshot:** cancel and offline. They use the same pending and error blocks as
the slow and 503 screens.

**Docs:** `tasks.md` adds Phase 12: T054 (task: mockups), T055 (task: build Graphite) and T056
(task: walkthrough in both themes), all done. T053 (task: `no_answer` notice kind) now notes
that the mock no longer relabels.

Mock servers I started on ports 8031 and 8032 are stopped.

Model spend: US$0, no model calls.

## 2026-10-13 15:20 — Addition to step 2: the composer clears on send

STATUS (to: orchestrator)

Done: "2026-10-13 15:12 — Addition to step 2: clear the composer on send". Rebuilt, and
http://localhost:8000 serves the new build (assets `index-CcjIb_F6.js` and
`index-CjUJB4j9.css`). Still stopped before T047 (task: cutover).

**What the user sees now.** Pressing Enter empties the composer at once. The question appears as
the user's bubble in the thread with "Finding an answer…" under it, and that turn scrolls into
view.

**The kept question, per request:**
1. **On send:** `copilot.question` keeps the sent question in `sessionStorage` until the answer
   arrives, so a reload mid-request still has it. Typing while a request is pending doesn't
   touch the stored value.
2. **If it isn't answered:** on cancel, `503`, offline, `422` or an expired session, the question
   goes back into the composer and into storage. That only happens if the composer is still
   empty.
3. **Text typed meanwhile:** if the user typed something new while the question was pending,
   that text stays and is what gets stored. It is never overwritten. On an answer, storage holds
   whatever is in the composer, or nothing.
4. **Sign-out** during a request clears everything, as before. The aborted request does not put
   the question back.

**How it's built.** `useAsk.send` now reports how a request ended: answered, failed, cancelled,
expired, or reset by sign-out. `App.tsx` handles the composer in one place, for typed questions,
clarify taps and Try again. The composer's text is also kept in a ref, because an expired session
unmounts the composer mid-request.

**Walkthrough.** New checks, all passing in light and dark:
- After send: the composer is empty, the pending turn's bubble shows the question, and
  `sessionStorage` holds it.
- After a `503`: the composer holds the question again. This check already existed; it now tests
  something real, because the composer is emptied on send.
- After cancel: the composer holds the question again (new screen 24, cancel puts the question
  back).
- Text typed while pending survives a cancel.

**Results:** first screen 1,874 ms (light) and 1,875 ms (dark) on Slow 4G; first load 126.2 kB
gzip. `tsc -b`, `eslint .`, Vitest (18 tests) and the mock tests (16) pass.
`screenshots-react/light/` and `/dark/` are regenerated, 28 screens each.

**Two problems found and fixed while checking the screenshots:**
- Chips for notices whose kind is `superseded`, `possibly_stale`, `bulletin` or `history` painted
  their tint on the whole 44 px tap box instead of the pill. Their class names clashed with the
  full notice blocks, so those rules now apply to `.notice` only.
- The first pending-turn scroll crashed in current Chrome. `scrollIntoView` now returns a value,
  and React took that value for an effect cleanup. The effect no longer returns it.

`tasks.md` adds T057 (task: clear the composer on send), done.

The mock server I started on port 8031 is stopped.

Model spend: US$0, no model calls.

## 2026-10-14 18:05 — T022: React walkthrough on the real API passes

STATUS (to: orchestrator)

Answers "2026-10-14 17:55 — T022: React walkthrough on the real API (user decision)", with
"17:58 — Spend caps lifted" and "17:59 — No switch to the larger model" read. T022 (task: run
the walkthrough against the real API) is done. The engine stayed on its configured models. I
changed nothing in the API, the engine or the client.

**Result.** The React build passes every check on real data: 28 screens at 375 px, light theme.

- No console errors, horizontal overflow, tap targets under 44 px, overlapping controls, or text
  under WCAG AA contrast.
- No withheld values on screen (see below), and no stray `null` or `undefined`.
- First screen on Slow 4G with a cold cache: 1,869 ms (limit 2,000 ms). First-load JS and CSS:
  126.2 kB gzip in 7 files (limit 170 kB). The real server gzips the build itself.
- Storage after the run: `localStorage` empty; `sessionStorage` holds only `copilot.question`.

No client bugs turned up. The first run reported four problems: one was a real-data difference
(listed below) and three were bugs in my new script, all fixed:

1. While a request is pending, no turn carries `answer-heading`. So after a clarify tap, the
   script's "current turn" fell back to the whole page and matched the earlier q04 turn (q04:
   casing bolt torque on FRS-P-0031, the Fresno HCP-350 pump). The script now waits for a new
   latest answer after every tap.
2. A missing pair of parentheses in a text read.
3. The check for the possibly-stale label looked for "stale". The client correctly shows
   "Possibly out of date".

**How to run**

```bash
cd web-react && npx -y npm@11 run build && cd ..   # unchanged build: index-CcjIb_F6.js
WEB_DIR=web-react/dist uv run python tests/api/serve_scratch.py --port 8010 &
node web/dev/screenshots_real.mjs                  # defaults: --base http://localhost:8010
```

The script is `web/dev/screenshots_real.mjs`. It keeps every check from `screenshots.mjs`, plus
the composer-empties-on-send check, run on a real ask while it's pending. It also prints each
ask's user, status and time.

**Adapted to real data.** These follow `tests/api/walkthrough_real.mjs`, except where noted.

- **Withheld values.** The mock's HCP-200 (Halden pump, 1998 German scan) rated head is
  OCR-verified in ds_0028 (dataset version 28), so it may be shown. Instead, the markers of
  HV-PROC-07 (VRS-110 drive fault reset procedure, restricted) must never be on screen for
  u01 (pump technician), u03 (compressor technician without high-voltage certification) or
  u09 (EU pump and conveyor technician). Those markers are P9.01 (drive parameter in
  HV-PROC-07), TP1 and TP2 (test points in HV-PROC-07), and "Rst En" (P9.01's display name).
  Users in cert-hv (permission group: high-voltage certified) are exempt.
- **q04 has no conflict** on real data. The engine returns `conflicts: []` and two bulletin
  notices: SB-2025-009 applies, SB-2025-018 doesn't. So the screen is named
  `03-answer-q04`, and the conflict check moved to u09's BX-12 (Belton conveyor) belt answer at
  Gdansk, which has one.
- **Scan.** The HCP-200 scanned page is opened from its citation chip. The check is that the
  sheet says "Scanned page", shows the English machine translation, and loads the page image.
  No passage in ds_0028 has an unverified marker, so "value unverified, see scanned page N"
  can't be exercised on real data.
- **Sources.**
  - Not visible: NK-600 (Nordkyl chiller) manual 8.4, SOP-020 (restricted refrigerant
    procedure), opened as u01.
  - Page number with no image: NK-600 page 11, opened as u06 (chiller technician without
    refrigerant certification).
- **VRS-75 oil** (Vastra compressor RTM-C-0121), asked by u03. The real answer has superseded
  and possibly-out-of-date sources, and both labels are checked. It has no steps and no
  undecided conflict, unlike the mock's.
- **Draft with no machine.** Mine, not in the 003 script. u03's "E-31 on a VRS-110" suggestion
  (E-31: compressor drive fault) already names a machine on real data, so the machine field
  is shown on u09's BX-12 draft instead. The suggestion names no machine. GDN-V-9999 gives the
  field error, with the typed value kept and no page error. Then gdn-v-0241 creates the draft
  for GDN-V-0241 (Gdansk BX-12, installed 2025).
- **Servio submit.** The BX-12 draft orders part 77-0419 (revised return idler), so it needs
  approval. 005 (work orders) finds no eligible approver: the only EU lead, u07 (EU
  compressor lead), doesn't cover conveyors. That screen is `15b-draft-parts-need-approval`.
  To reach the direct Servio submit, the script removes the part and saves. Then come the
  confirmation (`15-…`) and submitted (`16-…`) screens. The summary text still mentions the
  part, because it is the technician's free text.
- **Restricted, approval round trip, and session expiry** are the same steps as on the mock:
  - u03's E-31 on TAC-C-0143 (Tacoma VRS-110) is restricted, and the card uses the
    `/api/groups` description.
  - Draft, then Request approval.
  - u08 (NA team lead) approves with a note.
  - u03 sees the note and submits to MaintPro.

**Screenshots** are in `specs/004-mobile-web-client/screenshots-react-real/` (28 PNGs).

- Same file names as `screenshots-react/light/`, for the same screen: 01-sign-in, 02-ask-empty,
  04-source-bulletin, 08-source-not-visible, 10-restricted, 11-abstain, 12-clarify,
  13-draft-form-needs-approval, 13b-draft-choose-machine, 13c-draft-unknown-machine (both
  GDN-V here, not TAC-C), 14-draft-pending-approval, 14b-draft-approver-view,
  14c-draft-approved-with-note, 15-draft-confirm-servio, 16-draft-submitted, 19-session-expired,
  20-did-you-mean, 21-did-you-mean-answer-follow-up-bar, 22-new-question-cleared,
  23-follow-up-answering.
- New names where the screen differs:

| Real-data file | Replaces in the mock set | Why |
|---|---|---|
| 03-answer-q04 | 03-answer-q04-conflict | no conflict on real data |
| 05-answer-hcp200-scan | 05-unverified | no unverified value |
| 06-source-scan-translated | 06-source-scan-translated-with-marker | no marker |
| 07-source-shared-page-no-image | 07-source-superseded-no-image | NK-600 page 11 for u06 |
| 09-answer-vrs75-oil | 09-answer-steps-stale-undecided-conflict | real oil answer |
| 12b-clarify-answered | (new) | answer after picking FRS-P-0031 |
| 15a-answer-bx12-gdansk-conflict | (new) | the real conflict |
| 15b-draft-parts-need-approval | (new) | no eligible approver |

**Not covered** (mock-only keywords, skipped):
- 17-pending-slow (the "slow" keyword);
- 18-error-503 (the "fail" keyword);
- 24-cancel-question-back (it uses "slow").

`503` is covered by `tests/api`. The cancel and kept-question logic is covered by the mock
walkthrough.

**Server.** The real API ran on port 8010 with the React build. Work orders and audit rows went
to the scratch schema `wo_walk_0dc8d349`, which was dropped on exit. The 5 outbox files were in a
temporary folder, also removed. I stopped my server; port 8000 was never touched and is still
serving.

**Spend: US$0.0811**, measured by the server process's own meter (`process_spend_usd`), with a
US$0.30 per-process cap set before the caps were lifted. All uncached asks were in the first
run (about 17:52 to 17:53), before the evaluation's fresh run started at 17:58. Every later run
and API probe came from the model cache. The walkthrough makes 11 asks per run, with 9 distinct
questions. One caveat: the engine prices each call from the latest `data/usage.jsonl` row for
its prompt version (`_last_usage` in `llm.py`). With two processes calling at once, that can
pick up the other process's tokens. It didn't overlap here.

**Docs.** In `specs/004-mobile-web-client/tasks.md`, T022 is checked and reworded for the React
build and `screenshots_real.mjs`, and the dependency note is updated.

**Open items**
1. T047 (task: cutover: `web-react/` becomes `web/`) still waits for the user.
2. T023 (task: hide the test-user sign-in list in production) still waits on 003.
3. For you, not a client issue: no EU lead can approve a conveyor draft that orders parts
   (u07 covers compressors only). So on real data, EU conveyor drafts with parts can never be
   submitted. That's correct under 005's rules, but it may be a gap in the test users or the
   fleet setup.
