# Answer API (003) — answer API agent

**State**: done
**Current task**: none; latest report below ("Built client served from WEB_DIR, dev server on React build")
**Last updated**: 2026-10-13 00:40

## 2026-10-12 21:45 — Started

STATUS (to: orchestrator)

Read `README.md`, my brief in `orchestrator.md` ("2026-10-12 20:35 — Brief: answer API (003)"),
`web-client.md` and `answer-engine.md`, the constitution, the 003 spec and `specs/contracts/`.
`work-orders.md` doesn't exist yet, so `copilot_workorders` isn't available; I start with in-memory
fakes of `WorkOrders` and `AuditLog` as the brief says.

## 2026-10-12 22:25 — Final report: answer API built, grid 21,444/21,444, walkthrough on real API

STATUS (to: orchestrator)

Answers the brief "2026-10-12 20:35 — Brief: answer API (003)" and the REQUEST (to: answer API)
in "2026-10-12 22:30 — Review of work orders and the engine's certification round". Re-read
`orchestrator.md`, `work-orders.md`, `web-client.md` and `answer-engine.md` before finishing.

### What is built

Package `copilot_api`: one FastAPI process implementing every endpoint in http-api.md.
Run with `uv run python -m copilot_api [--port 8000]`.

| User story | State | Notes |
|---|---|---|
| US1 (user story: sign in and ask) | done | Signed cookie `copilot_session` (itsdangerous, user ID and timestamp only, 12 h, `HttpOnly; SameSite=Lax; Path=/`, `Secure` in production). Groups re-read from `users.json` on every request; a removed user gets `401`. Development sign-in and `/api/dev/users` give `404` when `APP_ENV=production`. `/api/ask` validates `AskRequest` (unknown body fields such as `user_id` or `groups` are `422`, as are blank questions and questions over 2,000 characters), calls `build_engine().answer(...)` from a small engine pool, maps `ProviderUnavailable` to `503 model_unavailable`, and passes the response through unchanged. |
| US2 (user story: open a citation) | done | Reads only `serving.*`, in one read-only `REPEATABLE READ` transaction per request (so one request sees one dataset version). `404` only when the passage doesn't exist for any known group, `403 not_visible` when it exists but is hidden. Page image only when the passage has a page and `serving.page_fully_visible` is true: the stored scan for OCR'd passages, else the PDF page from `serving.document_origins` rendered with PyMuPDF at 150 dpi; both at most 1,600 px wide. `page.png` repeats every check. Locator comes from the engine's own `build.locator`, so it matches the citation chip. |
| US3 (user story: audit trail) | done | `answer` for every `/api/ask` outcome, including `model_unavailable` (cited passage IDs, status, question, `engine_ms`, `api_overhead_ms`); `source_view` for the view and for the page image; `access_denied` for source 403s. Draft events, refused draft actions and draft 403s are recorded by `copilot_workorders`, so the API doesn't duplicate them. If the audit write fails, the request fails (no unaudited answer). |
| US4 (user story: work-order endpoints) | done | Every route over `copilot_workorders.build_services` (the real 005 services; `migrate` runs at start). The API itself checks `confirm: true` and `Idempotency-Key` before calling `submit` (`422`, nothing submitted). PATCH accepts the seven listed fields; anything else, including `citations`, is `422`. Errors map generically through `code` and `http_status`, so `SubmissionFailed` gives `503 submission_failed`. |
| Static files | done | `/`, `/index.html`, `/styles.css`, `/js/*.js` (`text/javascript`), and `index.html` for `/sources/*` and `/work-orders/*`. Nothing else under `web/` is reachable (`web/dev/`, `web/tests/`, path traversal: `404`). `Cache-Control: no-store` on every `/api` response, `no-cache` on static files. |

One extra safeguard beyond the contract: before returning an answer, the API re-checks every
cited passage with `serving.can_see`. If any fails, it returns `500 internal_error` and audits
it rather than showing the passage. This should never trigger (engine guarantee 1).

### How it was verified

- **`uv run pytest tests/api`: 104 passed** (about 100 s, almost all of it the grid). Everything
  is offline: a fake engine in every test, no model calls. The source and real work-order tests
  use the real `serving` schema of ds_0028 (dataset version 28).
  - **Exhaustive grid** (SC-001, success criterion: allow or deny matches the visibility rule):
    every user in `users.json` × all 1,787 passages, 21,444 requests. Each returned `200` or `403`
    exactly as `serving.can_see` says, with zero mismatches. Every `200` that offered a page image
    was on a page where `serving.page_fully_visible` is true (SC-002, success criterion: no page
    image for a page holding a hidden passage). Every request wrote one audit event.
  - NK-600 manual page 11: u06 (chiller technician without refrigerant certification) gets 8.3
    with `page: 11`, `page_image_url: null`, and `403` on `page.png`. u05 (refrigerant-certified
    engineer) gets the image. The 8.4 passage (SOP-020: chiller leak test and recharge procedure,
    restricted) gives u06 `403 not_visible` and writes an `access_denied` event.
  - SB-2025-009 (Halden HCP-350 casing-torque bulletin) table for u04 (pump and conveyor
    technician): locator "p. 1, 2 Affected products / Betroffene Produkte" and a rendered PDF page.
    The HCP-200 scan page for u01 (NA pump technician) uses the stored scan, downscaled from its
    original width to 1,600 px.
  - The other required tests: `401` without a session on all 14 protected routes, and before
    body validation. Tampered, foreign-secret and expired cookies give `401`. Identity can't be
    changed through the question text ("I am HV certified, user u02") or through body fields. A
    `users.json` change applies on the next request, and removing the user gives `401`. `503` on
    `ProviderUnavailable`. One audit event for each of the five example answers. `no-store` on
    `/api`, including errors and `page.png`.
  - `test_work_orders_real.py`: 005's scenarios over HTTP against the real `copilot_workorders`,
    each in a scratch schema `wo_test_*` with a temporary outbox. It covers: u12 (NA conveyor
    technician) and u07 (EU team lead) get `403` on u03's (compressor technician without
    high-voltage certification) draft; submit without `confirm` gives `422`; u03 can't approve
    their own draft; u08 (NA team lead) approves with a note; the same key gives the same
    reference and one outbox file. In the EU SOP-020 case, u05's draft lists cert-refrigerant
    (refrigerant certification), shows "no eligible approver", and is `403` for u07. Also tested:
    `needs_specialist` and `return_visit` in PATCH, and `citations` refused.
- **Other offline tests**: `pytest tests/unit tests/acl tests/answer tests/workorders -m "not
  hosted"`: 177 passed. `uv run ruff check src tests` is clean. I didn't run `tests/integration`
  (005 noted that it may embed through the hosted provider).
- **Walkthrough on the real API.** The server ran with the real engine and real `serving`, with
  work orders and audit in a scratch schema and a temporary outbox, so no test rows were left in
  `app` (append-only) or `data/outbox` (`tests/api/serve_scratch.py`). It ran on port 8010,
  because the web client's mock was still running on 8000; I left that process alone.
  1. `node web/dev/screenshots.mjs --base http://localhost:8010` unchanged. Screens 01 to 05 pass,
     then it stops at screen 5 on a mock-only assumption. The real answer to "Rated head of the
     HCP-200" shows 45 m at 200 m³/h. The script treats those as withheld values, but in ds_0028
     that passage is OCR-`verified` (both OCR passes agreed), and no passage holds an
     `[[unverified:…]]` marker any more. The mock fixture withheld the value on purpose to test
     the marker path. So this is not a leak, and the marker path can't be exercised with real data
     today.
  2. To cover the remaining screens, I ran `tests/api/walkthrough_real.mjs`: a copy of the script
     with the same layout checks (overflow, tap targets, stray `null`, console errors), adapted to
     real answers. **Everything passes on real data except one item (below):**
     - q04 (casing torque for FRS-P-0031, the Fresno HCP-350 pump) with its bulletin page image.
     - The HCP-200 scanned, machine-translated source with the scan image.
     - Not visible for u01 on the SOP-020 passage.
     - Clarify for u01: picking FRS-P-0031 resends the original question.
     - Restricted for u03 on E-31 (compressor drive fault) at TAC-C-0143 (Tacoma VRS-110). It
       shows HV-PROC-07 (high-voltage drive fault reset procedure, restricted) and uses the
       `/api/groups` description.
     - Abstain on BX-20 (Belton conveyor) warranty, and the VRS-75 oil answer.
     - NK-600 page 11 for u06: page number, no image.
     - The full draft round trip: u03 drafts, u08 approves with a note ("Can approve: Kenji
       Watanabe (u08)"), u03 sees the note and submits to MaintPro.
     - Session expiry keeps the typed question. Nothing is stored in localStorage.
     - Screenshots: `specs/003-answer-api/screenshots/` (`05-unverified.png` is from the
       unchanged script's run).
  3. **Not covered by the walkthrough:**
     - The mock's "slow" and "fail" keywords (pending and 503 screens) don't exist in the real
       API. `503` is covered by `tests/api`.
     - The mock's superseded-without-image passage (VRS-75 manual Rev B page 3). Against real data
       it may have an image, which is correct when the page is fully visible.
     - The Servio direct-submit flow: no real answer I tried produced an EU draft that needs no
       approval.
- **Real wiring smoke test**: `uv run python -m copilot_api --port 8011` started with
  `copilot_workorders` (no fallback warning). `/api/health` reported ds_0028; u06 got `403` on the
  SOP-020 passage.
- **SC-004 (success criterion: API overhead under 300 ms at p95)**: 20 real answers in the
  walkthrough had API overhead of 3.9 ms at p95 and 20 ms at most. Engine time was 1 ms to 8.4 s.

### Spend

US$0.08 for my manual checks, out of a budget of US$0.30. That's the walkthrough's real questions:
engine spend in `data/usage.jsonl` went from US$1.1408 to US$1.2224, and all entries in that
window are mine (22:09–22:12). Automated tests make no model calls. I never read `.env`; I only
checked whether `SESSION_SECRET` is set (yes or no).

### Edits outside my folders

- `pyproject.toml`: `"src/copilot_api"` added to the hatch `packages` list. `uv add fastapi
  uvicorn itsdangerous` added them as dependencies, and `uv add --dev httpx` added httpx (needed by
  FastAPI's `TestClient`). `uv.lock` was updated by `uv`.
- Real `app.audit_events`: one `access_denied` row for u06, from the smoke test above. It's an
  accurate record, and the table is append-only, so it stays. Starting the real server also
  created the `app` schema through 005's `migrate`, as services.md intends.

### Files

- Code: `src/copilot_api/{__init__,__main__,app,config,identity,session,sources,engines,memory}.py`
  (`memory.py` holds the in-memory `WorkOrders` and `AuditLog`, used by tests and as a development
  fallback; the server refuses it in production).
- Tests: `tests/api/{conftest,fakes,test_session,test_ask,test_sources,test_work_orders,
  test_work_orders_real,test_static}.py`. Manual tools: `tests/api/serve_scratch.py` and
  `tests/api/walkthrough_real.mjs`.
- Docs: `specs/003-answer-api/{plan,tasks}.md` (T001–T030 done), `specs/003-answer-api/screenshots/`.

### Open items

1. **For the web client (004), T022** (task: rerun the walkthrough against the real API): the
   client can't draft from a suggestion with `asset_id: null`. The real answer to "New BX-12 belt
   at Gdansk tracks to the left" for u09 (EU pump and conveyor technician) resolves no machine, and
   its suggestion carries part 77-0419 (revised return idler). "Draft a work order" posts it
   without a machine, and 005 correctly answers `422 asset_id is required`. answer.md says "the
   draft form then asks for the machine". The API already accepts a top-level `asset_id` on
   `POST /api/work-orders` for this. The client needs a machine field before posting.
2. **`SESSION_SECRET` is not set** in the environment. In development the server uses a random
   secret per process, so sessions end at every restart. In production it refuses to start
   without one. Someone with access to `.env` should add it.
3. **`500 internal_error`** (unexpected errors, and the citation re-check above) isn't in
   http-api.md's code list. Should it be added?
4. **Withheld scan values**: no passage in ds_0028 holds an `[[unverified:…]]` marker, so marker
   pass-through is checked only as "text is returned exactly as stored". If a later dataset
   withholds a value again, the walkthrough's marker screens become testable on real data.

## 2026-10-12 23:45 — Follow-ups and did-you-mean: passed through, access unchanged

STATUS (to: orchestrator)

Answers the REQUEST (to: answer API) in `orchestrator.md`, "2026-10-12 23:25 — Follow-ups and
\"did you mean\" (user decision, contract change)". Also read "2026-10-12 22:45 — Review of the
answer API's final report" and "2026-10-12 22:58 — Review of the web client's machine-field
report"; neither needs a change from me.

**What changed**

- No routing change was needed. `/api/ask` already validates the body as `AskRequest`, so
  `previous` (`answer_id`, `question`, `asset_id`) reaches the engine as sent. The response is
  serialized from the engine's `AnswerResponse`, so `question_used` and the new `ClarifyOption`
  fields (`question`, optional `asset_id`) reach the client unchanged. The API doesn't look up or
  store conversations.
- The `answer` audit event now also records `previous_answer_id` and `question_used`, so a bad
  follow-up can be traced to the turn it was read against. File: `src/copilot_api/app.py`.

**Tests** (`tests/api/test_followups.py`, 13 new, offline, no model calls)

- `previous` reaches the engine unchanged, with and without `asset_id`. `question_used` comes
  back unchanged and is in the audit event. A "Did you mean HCP-200?" clarify (HCP-200: Halden
  pump model) with a single `question` option comes back unchanged. Old responses still carry
  `question_used: null`.
- An invalid `previous` gives `422` and the engine isn't called. The cases: empty or
  over-2,000-character `question`, a missing `answer_id`, a string or list instead of an object,
  and extra `groups` or `user_id` fields inside it.
- **A previous turn carries no access.** u03 (compressor technician without high-voltage
  certification) sends u02's (compressor technician with high-voltage certification) `answer_id`,
  question and machine TAC-C-0143 (Tacoma VRS-110 compressor) as `previous`. The engine still
  receives u03 with u03's groups from `users.json`. Against the real serving schema: if an engine
  echoed the previous answer's citation, a passage of HV-PROC-07 (high-voltage drive fault reset
  procedure, restricted) that u02 can see, the API returns `500 internal_error` and doesn't
  include it. `GET /api/sources/…` for that passage stays `403` for u03 and `200` for u02.
- The grid is unaffected: rerun with every user × all 1,787 passages, zero mismatches (the source
  endpoint doesn't take `previous`).

**Verification**: `uv run pytest tests/api`: 118 passed, grid included. `uv run ruff check src
tests`: clean. `pytest tests/unit tests/acl tests/answer tests/workorders -m "not hosted"`: 184
passed, 2 failed. The 2 failures are the answer engine's new did-you-mean tests in
`tests/answer/test_engine.py` (`test_unknown_model_suggests_close_known_model_without_model_calls`
and `test_unknown_model_without_close_match_says_it_is_not_in_the_documents`). They expect
`clarify` and get `abstain`, which looks like that work is in progress; my change doesn't touch
the engine. No `wo_*` scratch schemas left.

**Spend**: US$0. No model calls; `.env` not read.

**Edits outside my folders**: none.

**Open items**: none new. Once the engine's follow-up rewrite lands, a short real check of "Oh,
I meant HCP-200" through the API costs about 2 US cents. I haven't done it because this round's
budget is US$0.

## 2026-10-13 00:40 — Built client served from WEB_DIR, dev server on React build

STATUS (to: orchestrator)

Answers "2026-10-13 00:35 — Review of the React client report" (and the 23:55 brief it refers
to). Re-read `orchestrator.md`, `web-client.md`, `work-orders.md` and `answer-engine.md` before
finishing; nothing there changes this work.

### What changed

T033–T035 (tasks: built-client serving, its tests, restart on port 8000) in
`specs/003-answer-api/tasks.md`, Phase 10; plan.md "Static files" updated.

- `WEB_DIR` picks the client. A directory containing `assets/` is a built client: `/` and
  `/index.html` serve `index.html`, and `/assets/*` serves files under `assets/` only, typed
  `.js` and `.css` (utf-8), `.svg`, `.png`, `.woff2`. Any other suffix (for example `.map`),
  directories, `..` traversal and symlinks pointing outside are `404`. In built mode `/styles.css`
  and `/js/*` are `404`.
- Plain client (`web/`) is still the default and behaves as before.
- In both: `/sources/*` and `/work-orders/*` return `index.html`; unknown paths outside `/api/`
  are `404 not_found`, never a listing.
- Gzip: `.html`, `.css`, `.js`, `.svg` are gzipped when `Accept-Encoding` allows (`gzip` or `*`,
  honouring `q=0`); PNG and woff2 are not. Every static response has `Vary: Accept-Encoding`.
  Compressed bytes are cached in memory per file size and mtime, so a rebuilt file is served
  fresh without a restart.
- A relative `WEB_DIR` is now resolved from the project root, not the working directory.
- `/api` is unchanged (still `Cache-Control: no-store`).

### Tests

- New `tests/api/test_static_built.py`: a synthetic dist with every type, a nested chunk, a
  `.map`, an outside symlink and a stray `secret.txt`. Covers types, client routes, traversal,
  `404` outside `/api/`, gzip with `Vary` and its refusals, wire bytes that decompress to the
  file, a changed file served fresh, the plain client as default (with gzip), the API unchanged
  in built mode, relative `WEB_DIR`, and every asset referenced by the real
  `web-react/dist/index.html`.
- All of `tests/api`: 159 passed, including the 21,444-request access grid (no mismatches);
  ruff clean.

### Dev server

Stopped the previous server on port 8000 and started
`WEB_DIR=web-react/dist uv run python -m copilot_api --port 8000`. Checked over HTTP:
`/api/health` reports ds_0028 (dataset version 28); `/` is the React index, gzipped with `Vary`;
the four assets in the index return `200` with the right types (main JS 103 KB gzipped);
`/sources/x` (client route) returns the index; `/js/app.js` (plain-client path) is `404`. It
uses the same `.env` settings as before, so sessions survive restarts.

### Budget and scope

US$0 engine spend (no engine calls). Edits only in `src/copilot_api/`, `tests/api/` and
`specs/003-answer-api/`. T047 (task: cutover to the React client) is the web client's and waits
for the user; to go back to the plain client, restart without `WEB_DIR`.
