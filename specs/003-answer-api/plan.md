# Implementation Plan: Answer API

**Branch**: `003-answer-api` | **Date**: 2026-10-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-answer-api/spec.md`; interface
`specs/contracts/http-api.md`.

## Summary

One FastAPI process between the phone client (004) and the in-process answer engine (002). It
signs technicians in with a signed cookie that carries only the user ID, looks their groups up in
`users.json` on every request, calls `copilot_answer.build_engine().answer(...)`, serves the
citation viewer through `serving.*` only, exposes the work-order endpoints through the
`copilot_contracts.services` interfaces (005), writes audit events, and serves `web/`.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI (Starlette), uvicorn, itsdangerous (cookie signing), psycopg 3
(already present), PyMuPDF (already present, page rendering and downscaling). Dev: httpx for
FastAPI's `TestClient`.

**Storage**: Postgres `copilot`: `serving` schema read-only through its functions and views;
`app` schema only through 005's `WorkOrders` and `AuditLog`. No tables of our own.

**Testing**: pytest, offline. Fake engine and in-memory `WorkOrders` / `AuditLog`; the source grid
and page tests run against the real published `serving` schema (skipped if the database is down).

**Target Platform**: local development server, `http://localhost:8000`.

**Project Type**: web service.

**Performance Goals**: SC-004 (success criterion: API overhead under 300 ms at p95 per answer).
The API adds a session check, a `users.json` read, one visibility query on the citations and one
audit write.

**Constraints**: no model calls in tests; never read `.env` (settings load it into the environment
through `copilot_ingest.settings`); `Cache-Control: no-store` on every `/api` response.

## Design

### Module layout

```text
src/copilot_api/
├── __init__.py      # create_app, build_app
├── __main__.py      # uv run python -m copilot_api [--port 8000]
├── config.py        # ApiConfig from the environment (APP_ENV, SESSION_SECRET, ...)
├── identity.py      # Directory: users.json re-read on every call
├── session.py       # signed cookie (itsdangerous), user ID + timestamp only
├── sources.py       # SourceStore over serving.*: source view, page image, dataset version
├── engines.py       # small pool of AnswerEngine instances (engine isn't thread-safe)
├── memory.py        # in-memory WorkOrders and AuditLog (tests; dev fallback until 005)
└── app.py           # routes, error mapping, Cache-Control, static files
tests/api/
├── conftest.py, fakes.py
├── test_session.py, test_ask.py, test_sources.py (grid, page rule), test_work_orders.py,
└── test_static.py
```

### Decisions

- **Session**: cookie `copilot_session`, value `URLSafeTimedSerializer(SESSION_SECRET).dumps(user_id)`,
  12 h max age, `HttpOnly; SameSite=Lax; Path=/` (plus `Secure` in production). A bad signature,
  an expired cookie or a user no longer in `users.json` gives `401`. Without `SESSION_SECRET`, the
  server refuses to start in production and uses a random per-process secret in development
  (sessions end at restart).
- **Identity**: `users.json` is parsed on every request (about 2 KB); no cache, so a change takes
  effect on the next request. `Identity` is built only from the session's user ID; the question
  text is never parsed for identity.
- **Dataset version per request**: each source request runs in one read-only `REPEATABLE READ`
  transaction, reading `serving.dataset_info()` in it, so one request sees one published version.
  Connections come from a small shared pool (a per-thread connection was reopened on every request
  under the test client, which made the grid take 6 minutes instead of 100 s).
- **Source existence vs visibility** (`404` vs `403`): the passage is read with the user's groups
  (`serving.passages_for`). Only if that returns nothing, the API asks whether it exists by calling
  `serving.passages_for` with every known group (the `users.json` catalog, plus the groups in
  `serving.document_origins` and `serving.restricted_procedures`) and keeps only the boolean. In
  ds_0028 (dataset version 28) every access alternative uses catalog groups, so this finds every
  passage.
- **Fail closed**: a visible passage whose document isn't in `serving.documents_for` is treated as
  not visible (none exist in ds_0028).
- **Page image**: offered only when the passage has a page, `serving.page_fully_visible` is true
  for it, and an image source exists: the passage's stored scan (`page_image`, relative to
  `DATA_DIR`) for OCR'd passages, else the first PDF in `serving.document_origins` rendered with
  PyMuPDF at 150 dpi. Both are scaled to at most 1,600 px wide. The `page.png` endpoint repeats
  every check. Rendered images are cached in process memory (they aren't user-specific; access is
  checked before the cache).
- **Locator** uses `copilot_answer.build.locator`, so the viewer shows the same label as the
  citation chip.
- **`superseded_by`**: the superseding document's ID from `serving.document_relations`, only if
  the user can see that document (`serving.can_see`), else `null`.
- **`possibly_stale`**: the passage flag or a `possibly_stale_vs` relation, as the engine does.
- **Answers pass through unchanged** (FR-004). Defence in depth: before returning, the API checks
  every cited passage with `serving.can_see`; if one fails it returns `500 internal_error` and
  audits it, rather than showing it. This should never happen (engine guarantee 1).
- **Engine pool**: `build_engine()` is called at start (so `ConfigurationError` stops the server)
  and lazily up to `ANSWER_ENGINES` (default 2) instances, one per concurrent request.
- **Audit**: `answer` (every `/api/ask` outcome, with cited passage IDs, status and the question),
  `source_view` (JSON view and page image), `access_denied` (source `403`, and `page.png` on a
  partly hidden page). Draft events, refused draft actions and draft `403`s are written by 005.
- **Work orders**: `copilot_workorders.build_services(DATABASE_URL)` and `migrate(conn)` at start
  when the package is importable; otherwise, outside production only, the in-memory
  implementation in `memory.py` with a warning. The API checks `confirm: true` and
  `Idempotency-Key` itself before calling `submit`. PATCH accepts `summary`, `work_steps`,
  `priority`, `fault_code`, `parts`, `needs_specialist`, `return_visit` (strict booleans); anything
  else, including `citations`, is `422`. Creation accepts only the fields `WorkOrders.create`
  takes.
- **Errors**: every non-2xx is `{"error", "detail"?}`; FastAPI validation errors become
  `422 invalid_request`; unknown routes `404 not_found`; unexpected exceptions
  `500 internal_error` (not in the contract's list; noted in the report).
- **Static files**: explicit routes for `/`, `/index.html`, `/styles.css`, `/js/<name>.js`, plus
  `index.html` for `/sources/*` and `/work-orders/*`; nothing else under `web/` is reachable.
  `WEB_DIR` (relative to the project root) selects the client; a directory with `assets/` is a
  built client, served as `index.html` plus files under `/assets/` only (`.js`, `.css`, `.svg`,
  `.png`, `.woff2`; anything else, symlinks out and directories are `404`). Text types are gzipped
  when `Accept-Encoding` allows, cached in memory per file size and mtime; every static response
  carries `Vary: Accept-Encoding`.

## Constitution Check

| Principle | How the design meets it |
|---|---|
| I. Authorization outside the model | Groups come only from `users.json` by the signed user ID; every source read is filtered by `serving.*` with those groups; page images require `page_fully_visible`; cited passages re-checked before returning an answer. |
| II. Grounded and verifiable | The source endpoint opens the exact passage with locator and page image; withheld values stay `[[unverified:…]]` markers (text passed through as stored). |
| III. Abstain rather than guess | Engine outcome passed through unchanged; `503 model_unavailable` instead of any fallback answer. |
| IV. Applicability by code | Not changed by the API; superseded and stale flags come from serving data. |
| V. Restricted procedures | No content of hidden passages is ever read for display; existence checks keep only a boolean. |
| VI. Humans commit | Submit requires `confirm: true` and an `Idempotency-Key`, checked by the API and by 005; every answer and source view audited. |
| VII. Measured | Exhaustive user × passage grid on the source endpoint; offline tests for every brief item. |
| VIII. Simplest architecture | One process, no gateway, no queue; in-process engine and services. |

No violations; no complexity tracking needed.
