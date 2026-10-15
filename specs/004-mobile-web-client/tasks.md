---

description: "Task list for the mobile web client"
---

# Tasks: Mobile Web Client

**Input**: Design documents from `/specs/004-mobile-web-client/`

**Prerequisites**: plan.md, spec.md, `specs/contracts/` (http-api.md, answer.md, work-orders-audit.md, examples/)

**Tests**: included: pure helper tests (node), mock endpoint tests (unittest), headless 375 px walkthrough.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup

- [x] T001 Create `web/` (index.html, styles.css, js/) and `web/dev/` layout per plan.md
- [x] T002 [P] Read the example passages once from ds_0026 into `web/dev/fixtures/sources.json`, with the HCP-200 head value replaced by an `[[unverified:…|page=3]]` marker
- [x] T003 [P] Write `web/dev/fixtures/mock_oil.json` (steps, stale and superseded citations, `preferred: null`, a 403 citation, EU asset) and validate it with `AnswerResponse.check()`

## Phase 2: Foundational

- [x] T004 Mock API `web/dev/mock_api.py`: static files, sessions (cookie `copilot_session`), `/api/dev/users`, `/api/health`, `no-store` on `/api`
- [x] T005 [P] `web/js/dom.js` builder (text nodes only) and `web/js/api.js` (same-origin fetch, timeout, `ApiError`)
- [x] T006 [P] `web/js/text.js` pure helpers: marker parsing, citation order, step grouping, labels
- [x] T007 `web/js/app.js` hash router, session check, sign-in screen from test users (FR-009), sign out clears memory
- [x] T008 [P] `web/styles.css`: 375 px layout, 44 px targets, high contrast, focus rings, reduced motion

## Phase 3: User Story 1 - Ask and read on a phone (P1) 🎯 MVP

**Independent Test**: each example renders at 375 px via the mock.

- [x] T009 [US1] Mock `/api/ask` keyword routing to the five examples, `slow` (8 s) and `fail` (503)
- [x] T010 [US1] Ask screen with bottom composer, pending state with slow hint and cancel, kept question, retry, 503 / no-connection / 422 / expired-session messages
- [x] T011 [US1] `web/js/answer.js`: machine header with bulletins, statements, numbered steps, warnings, citation chips, notices
- [x] T012 [US1] Restricted card (procedure, missing groups in plain words, Draft a work order), abstain card distinct from errors, clarify options resending `asset_id` + `clarification_of`

## Phase 4: User Story 2 - Check the source (P1)

**Independent Test**: every chip opens its viewer; 403 shows "Not visible to you".

- [x] T013 [US2] Mock `/api/sources/{id}` and `/page.png` (real HCP-200 page 3 scan, placeholder PNG otherwise, 403 for p_0ee8e5f1561408d13db4a416, 404 unknown)
- [x] T014 [US2] `web/js/source.js`: title, revision, issue date, locator, superseded / possibly stale / scanned / machine-translated labels, original + English, page image only when `page_image_url` is set, 403 and 404 cards
- [x] T015 [US2] Unverified segments and source markers render only as "value unverified, see scanned page N" linking to the viewer's page image

## Phase 5: User Story 3 - Conflicts and notices (P2)

- [x] T016 [US3] Conflict card: both sides with chips; preferred marked with reason; `preferred: null` marks none and says to check with a lead

## Phase 6: User Story 4 - Draft a work order (P3)

**Independent Test**: from restricted.json create a draft, edit the summary, request approval.

- [x] T017 [US4] Mock work orders in memory: create, get, list, patch, request-approval, approve, reject, idempotent submit; approval reasons and eligible approvers per region
- [x] T018 [US4] `web/js/workorder.js`: prefilled form, approval box (who and why), Request approval vs Submit, approve/reject for leads, confirmation dialog naming MaintPro or Servio, `Idempotency-Key` from the draft

## Phase 7: Polish & Verification

- [x] T019 [P] `web/tests/text.test.mjs` (node --test): markers withheld, unverified text dropped, citations listed, flags
- [x] T020 [P] `web/dev/test_mock_api.py` (unittest): sessions, routing, sources, approval flow, Servio submit, no eligible approver
- [x] T021 `web/dev/screenshots.mjs`: 19 screens (23 with T052) at 375 px into `screenshots/`, failing on console errors, overflow, small targets, stray `null`, or the withheld value on screen
- [x] T022 Walkthrough of the React build against the real 003 API (orchestrator request 2026-10-14 17:55): `web/dev/screenshots_real.mjs` against `WEB_DIR=web-react/dist uv run python tests/api/serve_scratch.py --port 8010`, light theme, 28 screens into `screenshots-react-real/`; same checks as `screenshots.mjs`, with the withheld check on HV-PROC-07's markers for users without cert-hv; all pass (1,869 ms first screen, 126.2 kB gzip). Not covered: the mock's "slow" and "fail" keywords (screens 17, 18, 24)
- [ ] T023 Remove or gate the sign-in user list when 003 reports `APP_ENV=production` (depends on how 003 exposes the dev user list)

## Phase 8: Contract changes (orchestrator decision 2026-10-12 20:30)

- [x] T024 Mock: `/api/dev/users` returns only `users`; new `GET /api/groups` (needs a session); error codes per http-api.md "Errors"
- [x] T025 Mock: `eligible_approvers` and `decision_note` on drafts; every draft validated against `WorkOrderDraft` in `web/dev/test_mock_api.py`
- [x] T026 [US1] Restricted card uses `/api/groups` descriptions (`setGroupWords`), with `GROUP_WORDS` as offline fallback
- [x] T027 [US4] Draft screen: "Can approve" names from `eligible_approvers`, approver check from that list, optional note on approve/reject, `decision_note` shown
- [x] T028 Walkthrough: approval round trip (u03 requests, u08 approves with a note, u03 submits to MaintPro); screenshots 14b and 14c

## Phase 9: Suggestions without a machine (orchestrator request 2026-10-12 22:45)

- [x] T029 Mock: "E-31" without a TAC-C asset ID returns restricted with `asset: null` and `work_order_suggestion.asset_id: null`; `POST /api/work-orders` takes a top-level `asset_id` (required when the suggestion has none, must match when it has one, unknown machine `422 invalid_request` as in the real API)
- [x] T030 [US4] `mountNewDraft` in `web/js/workorder.js`: when the suggestion has no machine, ask for the asset ID first; `404`, `403` and asset-related `422` show as a field error with the typed value kept (`assetFieldError` in `web/js/text.js`)
- [x] T031 [US4] Align with 005 (work orders): `needs_specialist` and `return_visit` checkboxes; `503 submission_failed` message on submit
- [x] T032 Tests: mock `test_draft_needs_a_machine_when_none_was_resolved`, `test_specialist_and_return_visit_need_approval`; node tests for `assetFieldError` and `normalizeAssetId`; walkthrough screens 13b and 13c

## Phase 10: Migration to React (owner decision 2026-10-12)

**Purpose**: rebuild the client in React with shadcn/ui and AI Elements (plan.md, "Migration to
React" and Complexity Tracking). Behaviour and contracts stay the same; the plain client stays in
service until T047.

**Independent Test**: the built client in `web-react/dist/`, served by the mock, passes the
unchanged walkthrough and mock tests, plus the SC-004 (success criterion: first screen under 2 s on
a slow connection) timing and the 170 KB gzip budget.

### Setup

- [x] T033 Create `web-react/` (Vite, React 19, TypeScript strict) with pinned versions, ESLint with `react/no-danger` as an error, dev proxy `/api` -> `http://localhost:8000`, build to `web-react/dist/`
- [x] T034 [P] Tailwind CSS v4 and shadcn/ui (`components.json`); tokens carried over from `web/styles.css`: high contrast, focus rings, 44 px minimum targets, theme follows the system setting with nothing persisted
- [x] T035 [P] Add AI Elements with the shadcn CLI: conversation, message, prompt-input, inline-citation, sources, suggestion, confirmation, shimmer; strip the Streamdown markdown path from `message` so answer text can only be rendered as text (done: trimmed further, no `motion`, no `use-stick-to-bottom`, no hover cards; each file's header says what was removed)
- [x] T036 [P] Add `--web DIR` to `web/dev/mock_api.py` (default `web/`), keeping the rule that it never serves `dev/` or `tests/`; cover it in `web/dev/test_mock_api.py`
- [x] T037 [P] Generate `web-react/src/lib/contract.ts` from `specs/contracts/examples/answer-response.schema.json` with a `npm run contract` script, and type-check the five example responses against it (done: seven, the five examples plus the two `mock_*` fixtures, in `src/lib/contract.examples.ts`)

### Foundational

- [x] T038 Port `web/js/text.js` to `src/lib/text.ts` and `web/js/api.js` to `src/lib/api.ts`; port `web/tests/text.test.mjs` to Vitest with every case kept (markers withheld, unverified text dropped, unclosed marker hides the rest, citation order, labels, group words)
- [x] T039 `src/main.tsx`: TanStack Query client kept in memory only (no persister; retry only on network errors and `503`), hash router for `#/signin`, `#/ask`, `#/sources/{id}[/page]`, `#/work-orders/{id}`, path-to-hash rewrite, session check, sign-in list from `/api/dev/users` with the user ID field fallback (FR-009: development sign-in), `/api/groups` loaded once per session

### User Story 1 - Ask and read on a phone

- [x] T040 [US1] Ask screen with `Conversation` and `PromptInput`, named "Handy Manual" with the hint "Ask the Handy Manual"; Enter sends, Shift+Enter adds a line, nothing is sent while a keyboard is composing; pending state with `Shimmer`, slow hint and cancel (aborts the request), question kept in `sessionStorage` only, messages for `503`, no connection, `422` and expired session (`401` keeps the question)
- [x] T041 [US1] `AnswerView`: machine header with bulletins, statements, numbered steps, warnings, `InlineCitation` chips numbered by first use, notices; `RestrictedCard` with missing groups in plain words and "Draft a work order"; abstain card distinct from errors; clarify options with `Suggestion`, resending `asset_id` and `clarification_of`

### User Story 2 - Check the source

- [x] T042 [US2] `SourceSheet` (Vaul bottom sheet, also reachable by its own route): title, revision, issue date, locator, labels as badges (superseded, possibly stale, scanned, machine-translated), original and English, page image only when `page_image_url` is set with pinch-zoom (react-zoom-pan-pinch, lazy-loaded), "Not visible to you" on `403`, "not found" on `404`; `UnverifiedValue` renders only "value unverified, see scanned page N" linking to the page image (FR-002: withheld values never displayed)

### User Story 3 - Conflicts and notices

- [x] T043 [US3] `ConflictCard`: both sides with chips; preferred side marked "Applies to this machine" with the reason; `preferred: null` marks no side and says to check with a lead

### User Story 4 - Draft a work order

- [x] T044 [US4] `DraftSheet` (Vaul, lazy-loaded): when the suggestion has no machine, ask for the asset ID first with field errors as in T030; React Hook Form with Zod limited to the editable fields (`summary`, `work_steps`, `priority`, `fault_code`, `parts`, plus the `needs_specialist` and `return_visit` checkboxes from T031), `503 submission_failed` message on submit, approval box from `approval_reasons` and `eligible_approvers`, approve or reject with an optional note for eligible approvers, `decision_note` shown, `Confirmation` naming MaintPro or Servio before submit (FR-006: explicit confirmation), `Idempotency-Key` from the draft, Sonner toasts for state changes

### Verification and cutover

- [x] T045 Walkthrough against the built client (`npm run build`, mock with `--web web-react/dist`): adapt only selectors in `web/dev/screenshots.mjs`, keep every check, add first-screen timing under emulated Slow 4G (fails over 2 s) and a gzip size check of first-load JavaScript and CSS (fails over 170 KB); all screens and `uv run python -m unittest web/dev/test_mock_api.py` pass (done: 1,877 ms and 126.1 kB gzip; the mock now gzips static files when the browser accepts it. The plain client takes 3,055 ms on the same check)
- [x] T046 (decided by the orchestrator 2026-10-12 23:55; http-api.md now covers `WEB_DIR`) Contract change: web client agent writes a `REQUEST (to: orchestrator)` in `specs/coordination/web-client.md` for the "Static files and client routes" wording in plan.md, "Migration to React"; the orchestrator records the `DECISION` and edits `specs/contracts/http-api.md`
- [x] T047 Cutover, done differently by the user's choice: `web-react/` keeps its name, `web/dev/` moved to `web-react/dev/`, the plain client (`web/`) deleted, the API and mock default to `web-react/dist/`, Running section updated; screenshots not regenerated (kept out of git)

## Phase 11: Follow-ups and "did you mean" (orchestrator request 2026-10-12 23:25)

Done in the plain client. The React tasks above (T040–T042, T045) carry the same behaviour: the
walkthrough checks in T048–T052 are part of the bar in T045.

- [x] T048 Mock: `AskRequest.previous` validated (422 on bad shape or unknown keys); follow-up phrasings ("oh", "and", "what about", "I meant"…) rewritten against `previous.question`, with `question_used` set and `previous.asset_id` carried unless the follow-up names a machine; a machine named in the question that differs from the canned answer's machine gets a "no canned answer" abstain instead of the wrong machine
- [x] T049 Mock: unknown model names one character off a known one (HCP-20) return a clarify "Did you mean HCP-200?" with `question` options; no close match returns an abstain; new fixture `mock_hcp200_clearance.json`
- [x] T050 [US1] Client: the answer on screen is sent as `previous` (`previousTurn` in `web/js/text.js`); a "New question" button above the composer clears it, as do sign-out and reload (answers are in memory only); "Answering: …" shown when `question_used` differs from the typed text; clarify options with `question` resend that text, machine options resend with `asset_id` and `clarification_of`, both keeping `previous` (`clarifyRequest`)
- [x] T051 [US1] Client: on abstains whose reason isn't `not_visible`, a `not_visible` notice is titled "Why there's no answer" (the engine labels every abstain notice `not_visible`); `no_permitted_source` reads "Your sources don't cover this."
- [x] T052 Tests: mock `test_did_you_mean_then_follow_up`, `test_unknown_model_without_close_match_abstains`, `test_follow_up_new_topic_switch_machine_and_restricted`, `test_previous_is_validated`, every ask body checked against `AskRequest` and responses against `AnswerResponse.check()`; node tests for `previousTurn` and `clarifyRequest`; walkthrough screens 20–23
- [x] T053 [US1] `no_answer` notice kind (orchestrator decision 2026-10-12 23:50): titled "Why there's no answer"; the guard for `not_visible` notices on other abstains stays; the mock emits `no_answer` for every abstain except `not_visible` (since 2026-10-13 `examples/abstain.json` carries `no_answer` itself, so the mock no longer relabels it)

## Phase 12: UI overhaul, Graphite (orchestrator decisions 2026-10-13 13:45 and 14:50)

- [x] T054 Mockups of three directions in `design/` with `web/dev/mockups.mjs` (overflow, 44 px controls, overlap, WCAG AA contrast in light and dark, text sizes); the user picked Graphite
- [x] T055 [US1] [US2] [US4] Graphite in `web-react/`: light and dark tokens, the Handy Manual mark, a thread of turns cleared by New question, sign-out or reload (one `previous` sent), answer text first with machine, bulletins and notices as expandable chips, one citation control per sentence opening the source sheet with a keyboard and screen-reader switcher (the sheet's own route opens one passage), restyled source sheet, draft sheet and confirmation
- [x] T056 Walkthrough: overlap and contrast checks from `mockups.mjs`, `--theme light|dark` via emulated `prefers-color-scheme`, selectors scoped to the current turn; `screenshots-react/light/` and `screenshots-react/dark/` regenerated, all checks pass (1,868 ms and 1,870 ms first screen, 126.0 kB gzip)
- [x] T057 [US1] Composer clears on send (orchestrator request 2026-10-13 15:12): the question shows at once as the pending turn's bubble and stays in `sessionStorage` until answered; on cancel, `503`, offline, `422` or an expired session it goes back into the composer unless the user typed something new meanwhile, which is never overwritten; walkthrough checks after send, `503` and cancel (screen 24)

## Dependencies & Execution Order

Setup → Foundational → US1 → US2 (needs answer chips) → US3 → US4 (needs restricted card) → Polish.
T023 waits for 003. T022 is done against the React build in `web-react/dist`.

Phase 10: T033 first; T034–T037 in parallel; T038–T039; then T040–T044 in story order; T045; T047
after T045 passes and T046 is decided.
