# Tasks: Answer API

**Input**: `specs/003-answer-api/spec.md`, `plan.md`; interface `specs/contracts/http-api.md`

**Tests**: required by the brief (orchestrator.md, "Brief: answer API (003)"); all offline, no
model calls. The source grid and page tests use the real `serving` schema.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup

- [x] T001 Add FastAPI, uvicorn, itsdangerous (runtime) and httpx (dev) with `uv add`; add
  `"src/copilot_api"` to the hatch `packages` list in `pyproject.toml`
- [x] T002 Create `src/copilot_api/` and `tests/api/` packages

## Phase 2: Foundational

- [x] T003 `src/copilot_api/config.py`: `ApiConfig` from the environment; refuse to start in
  production without `SESSION_SECRET`
- [x] T004 [P] `src/copilot_api/identity.py`: `users.json` directory re-read on every call
- [x] T005 [P] `src/copilot_api/session.py`: signed cookie carrying only the user ID
- [x] T006 `src/copilot_api/app.py`: error body `{"error", "detail"?}` for every non-2xx,
  `Cache-Control: no-store` on `/api`, session dependency that runs before body validation
- [x] T007 [P] `tests/api/conftest.py`, `tests/api/fakes.py`: harness with fake engine, fake
  sources and in-memory services

## Phase 3: User Story 1 - Sign in and ask (P1)

- [x] T008 [US1] Session endpoints, `/api/dev/users` (404 in production), `/api/groups`,
  `/api/health` in `app.py`
- [x] T009 [US1] `/api/ask`: validate `AskRequest` (422, including blank and over 2,000
  characters), call the engine with the session identity, `503 model_unavailable` on
  `ProviderUnavailable`, pass the response through unchanged
- [x] T010 [US1] `src/copilot_api/engines.py`: engine pool (`ANSWER_ENGINES`, default 2)
- [x] T011 [US1] Re-check every cited passage with `serving.can_see` before returning an answer
- [x] T012 [P] [US1] `tests/api/test_session.py`: 401 everywhere without a session, tampered,
  foreign-secret and expired cookies, production sign-in disabled, `users.json` change applies on
  the next request
- [x] T013 [P] [US1] `tests/api/test_ask.py`: identity not changeable through question text or
  body fields, 422 cases, 503, pass-through, `Cache-Control`

## Phase 4: User Story 2 - Open a citation (P1)

- [x] T014 [US2] `src/copilot_api/sources.py`: source view through `serving.*` in one read-only
  transaction; 404 vs 403; locator from `copilot_answer.build.locator`; `superseded_by` only when
  visible
- [x] T015 [US2] Page images: stored scan for OCR'd passages, PDF page via PyMuPDF at 150 dpi,
  both at most 1,600 px wide; only when `serving.page_fully_visible`; in-memory render cache
- [x] T016 [US2] `tests/api/test_sources.py`: exhaustive user × passage grid (SC-001, SC-002),
  NK-600 manual page 11 for u06 and u05, SOP-020 passage 403, SB-2025-009 table, HCP-200 scan
- [x] T017 [US2] Speed up the 403 path (existence check 9.5 ms → 0.3 ms)

## Phase 5: User Story 3 - Audit trail (P2)

- [x] T018 [US3] Audit events: `answer` (every outcome, including 503), `source_view` (view and
  page image), `access_denied` (sources and drafts)
- [x] T019 [US3] Tests: one event per answer with cited IDs and status; grid checks one event per
  source request

## Phase 6: User Story 4 - Work-order endpoints (P2)

- [x] T020 [US4] Work-order routes over `WorkOrders`; API-side checks for `confirm: true`,
  `Idempotency-Key` and editable fields
- [x] T021 [US4] `src/copilot_api/memory.py`: in-memory `WorkOrders` and `AuditLog` (tests;
  development fallback until 005)
- [x] T022 [US4] `tests/api/test_work_orders.py`: 403 for u12 on u03's draft, submit 422 cases
  with nothing submitted, approval round trip, idempotent submit

## Phase 7: Polish

- [x] T023 Static files and client routes; `tests/api/test_static.py`
- [x] T024 `src/copilot_api/__main__.py`: `uv run python -m copilot_api`
- [x] T025 Switch to `copilot_workorders.build_services` and `migrate` (in `__init__.py`; the
  in-memory services remain only as a development fallback, refused in production);
  `tests/api/test_work_orders_real.py` runs the 005 scenarios over HTTP in a scratch schema
- [x] T026 Run the web client walkthrough against the real API: `web/dev/screenshots.mjs`
  unchanged, then `tests/api/walkthrough_real.mjs` (adapted to real answers) on
  `tests/api/serve_scratch.py` (scratch schema and temporary outbox); screenshots in
  `specs/003-answer-api/screenshots/`

## Phase 8: Orchestrator review "2026-10-12 22:30 — Review of work orders and the engine's certification round"

- [x] T027 `SubmissionFailed` (503 `submission_failed`) mapped generically through `code` and
  `http_status`; test
- [x] T028 PATCH accepts `needs_specialist` and `return_visit` (strict booleans); tests with the
  in-memory and the real services
- [x] T029 PATCH refuses `citations` with `422`; tests
- [x] T030 Stop writing `access_denied` for draft 403s in the API: 005 records them itself

## Phase 9: Orchestrator decision "2026-10-12 23:25 — Follow-ups and \"did you mean\""

- [x] T031 Pass `AskRequest.previous` to the engine and `AnswerResponse.question_used` to the
  client unchanged (no API state); record `previous_answer_id` and `question_used` in the
  `answer` audit event
- [x] T032 `tests/api/test_followups.py`: both round-trip, a "did you mean" clarify option with
  `question` round-trips, invalid `previous` is `422`, another user's `previous` changes neither
  identity nor passage access (real serving schema); grid rerun

## Phase 10: Orchestrator review "2026-10-13 00:35 — Review of the React client report"

- [x] T033 Serve a built client from `WEB_DIR` per http-api.md "Static files and client routes":
  `/assets/*` with typed `Content-Type`, client routes to `index.html`, gzip with `Vary` for
  both clients; relative `WEB_DIR` resolved from the project root
- [x] T034 `tests/api/test_static_built.py`: types, client routes, no traversal or symlink
  escape, `404` outside `/api/`, gzip negotiation and `Vary`, plain client still the default,
  API unchanged, every asset of the real `web-react/dist`
- [x] T035 Restart the dev server on port 8000 with `WEB_DIR=web-react/dist`
