# Implementation Plan: Mobile Web Client

**Branch**: `004-mobile-web-client` | **Date**: 2026-10-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/004-mobile-web-client/spec.md`

## Summary

A single-page phone client for field technicians: development sign-in, ask, read an answer in
every status of `specs/contracts/answer.md`, open any citation in a source viewer, see conflicts,
warnings and unverified values, pick a machine when asked, and turn a `work_order_suggestion` into
a draft (005) that is submitted or sent for approval only after an explicit confirmation.

Plain HTML, CSS and ES modules served as static files by the 003 API at `/`, talking to `/api/...`
on the same origin. No build step, no CDN, no npm packages. Until 003 exists, a standard-library
mock (`web/dev/mock_api.py`) serves the client and canned responses built from
`specs/contracts/examples/` and real ds_0026 (dataset version 26) passages.

**Revision 2026-10-12 (owner decision):** the client moves to React, built with Vite into static
files that 003 serves the same way. The plain client stays in service until the React client passes
the same checks (see "Migration to React" and Complexity Tracking). The behaviour, the contracts and
the requirements in spec.md do not change.

## Technical Context

**Language/Version**: TypeScript (strict) and React 19, compiled by Vite to ES2022 for evergreen mobile browsers (Safari iOS 16+, Chrome Android); Python 3.12 standard library for the mock. The current plain client is JavaScript (ES2022 modules) with no build.

**Primary Dependencies** (React client):
- UI: Tailwind CSS v4, shadcn/ui (Radix primitives, copied into the repo), AI Elements (`Conversation`, `Message`, `PromptInput`, `InlineCitation`, `Sources`, `Suggestion`, `Confirmation`, `Shimmer`; copied in by the shadcn CLI), Lucide icons, Sonner toasts
- Phone interaction: Vaul (bottom sheets for the source viewer and draft), react-zoom-pan-pinch (scanned page images), Motion (transitions, off under reduced motion)
- Data and forms: TanStack Query (in memory only), React Hook Form with Zod
- Routing: React Router in hash mode (`createHashRouter`), keeping today's `#/…` routes

**Storage**: in-memory only for answers, sources and drafts; `sessionStorage` holds only the typed question (`copilot.question`) so a reload or expired session keeps it (FR-008 forbids storing answers or sources). In the React client: no TanStack Query persister, no theme persistence (the theme follows the system setting), nothing in `localStorage`.

**Testing**: `node --test web/tests/*.test.mjs` (pure rendering helpers); `uv run python -m unittest web/dev/test_mock_api.py` (mock endpoints over HTTP); `node web/dev/screenshots.mjs` (headless Chrome walkthrough at 375 px over the DevTools protocol, no packages). React client: the helper tests move to Vitest; the mock tests and the walkthrough stay as they are and are pointed at the built client.

**Target Platform**: phone browsers at customer sites, 375 px wide and up

**Project Type**: static web client served by the 003 API (React client: Vite build output served the same way)

**Performance Goals**: first screen under 2 s on a slow mobile connection (SC-004). Plain client: about 65 KB uncompressed across 9 files, no fonts or images on first load. React client budget: at most 170 KB gzip of JavaScript and CSS on first load; the source viewer, pinch-zoom and draft form are lazy-loaded; no web fonts; measured in the walkthrough under emulated Slow 4G

**Constraints**: one-handed use, tap targets ≥ 44 px, outdoor contrast, unreliable connectivity (pending state, retry, kept question), never show a value or passage the server didn't send

**Scale/Scope**: 5 screens (sign-in, ask/answer, source viewer, draft form, confirmation)

## Constitution Check

| Principle | How the client meets it |
|---|---|
| I. Authorization outside the model | The client holds no access logic. Identity is the session cookie; groups come from the server. A `403` renders "Not visible to you" (never "doesn't exist"); `404` is the only "not found". Page images are shown only when `page_image_url` is not null. |
| II. Grounded and verifiable | Every sentence, conflict side, notice and bulletin gets numbered citation chips (≥ 44 px) that open the exact passage in the viewer; a numbered Sources list repeats title, locator and flags. |
| III. Abstain rather than guess | `abstain` renders as a neutral "No answer from your sources" card, visually and textually distinct from errors; `clarify` resends with `asset_id` and `clarification_of`. |
| IV. Applicability by code; conflicts shown | Both sides of every conflict are shown; the `preferred` side is marked "Applies to this machine" with the reason; `preferred: null` marks no side and says to check with a lead. Superseded and possibly-stale sources are labelled in the answer and the viewer. |
| V. Restricted procedures | `restricted` shows only the procedure name and missing groups in plain words, plus "Draft a work order". The client never asks for or renders restricted content. |
| VI. Humans commit | Submit opens a modal naming MaintPro or Servio; nothing is sent until "Send to MaintPro/Servio" is pressed. The draft's `idempotency_key` is sent as `Idempotency-Key`, so a retry after a dropped connection can't duplicate. |
| VII. Measured | The headless walkthrough fails on console errors, overflow at 375 px, small tap targets, stray `null` text, or the withheld HCP-200 head value appearing anywhere on screen. |
| VIII. Simplest architecture | Plain client: no framework, no build, no service worker, no client cache. React client: adds a framework and a build step, justified in Complexity Tracking; still no service worker, no client cache, no extra service (the build output is static files served by 003). |

Withheld values (contracts README rule 6): `[[unverified:…]]` markers in source text and
`unverified` answer segments render only as "value unverified, see scanned page N" linking to the
viewer's page image; any text inside an unverified segment is dropped, and an unclosed marker hides
the rest of the passage. Tested in `web/tests/text.test.mjs`.

Plain client: no violations. React client: one justified exception to Principle VIII (simplest
architecture), recorded in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/004-mobile-web-client/
├── spec.md
├── plan.md              # this file
├── tasks.md
└── screenshots/         # 375 px walkthrough output (node web/dev/screenshots.mjs)
```

### Source Code (repository root)

```text
web/
├── index.html           # shell: top bar, <main>, live region, toast
├── styles.css           # phone-first, high-contrast, 44 px targets
├── js/
│   ├── app.js           # router (#/signin, #/ask, #/sources/{id}[/page], #/work-orders/{id}), state, ask flow, errors
│   ├── api.js           # fetch wrapper: same-origin, no-store, 60 s timeout, ApiError(status, code)
│   ├── answer.js        # AnswerResponse rendering for all four statuses
│   ├── source.js        # source viewer, 403 / 404 cards
│   ├── workorder.js     # draft form, approval, confirmation dialog, idempotent submit
│   ├── text.js          # pure helpers: marker parsing, citation order, labels (node-testable)
│   └── dom.js           # h() builder; text only via text nodes, never innerHTML
├── tests/
│   └── text.test.mjs    # node --test
└── dev/                 # development only; the mock refuses to serve this folder
    ├── mock_api.py      # stdlib mock of http-api.md on :8000
    ├── test_mock_api.py # unittest over HTTP
    ├── screenshots.mjs  # headless Chrome walkthrough at 375 px
    └── fixtures/
        ├── sources.json # source views for every example citation (from ds_0026)
        └── mock_oil.json# mock-only answer: steps, stale + superseded, preferred: null, 403 citation, EU asset
```

**Structure Decision**: one static folder `web/` that 003 mounts at `/`; development tooling in
`web/dev/` only.

React client, built next to the plain one until cutover (there is no git branch to work on):

```text
web-react/
├── package.json         # pinned versions; scripts: dev, build, test, typecheck, lint
├── vite.config.ts       # base "/", outDir dist/, dev proxy /api -> http://localhost:8000
├── index.html
├── components.json      # shadcn/ui and AI Elements configuration
├── src/
│   ├── main.tsx         # QueryClient (memory only), hash router
│   ├── routes/          # signin, ask, source viewer, work order
│   ├── components/
│   │   ├── ui/          # shadcn/ui (copied in)
│   │   ├── ai-elements/ # AI Elements (copied in)
│   │   └── copilot/     # AnswerView, ConflictCard, RestrictedCard, UnverifiedValue, SourceSheet, DraftSheet
│   ├── lib/
│   │   ├── api.ts       # port of api.js: same-origin fetch, 60 s timeout, ApiError
│   │   ├── text.ts      # port of text.js: marker parsing, citation order, labels
│   │   └── contract.ts  # types generated from specs/contracts/examples/answer-response.schema.json
│   └── styles.css       # Tailwind entry, design tokens
├── tests/               # Vitest: text.test.ts (port of web/tests/text.test.mjs)
└── dist/                # build output, the only folder 003 serves
```

At cutover `web-react/` replaces `web/`; `web/dev/` (mock, fixtures, mock tests, walkthrough) moves
across unchanged.

## Design decisions

- **Routing in the hash.** `viewer_url` in the contract is `/sources/{id}`; the client links to
  `#/sources/{id}` so 003 needs no SPA fallback. If a user lands on `/sources/{id}` as a path, the
  client rewrites it to the hash route (the mock serves `index.html` for `/sources/*` and
  `/work-orders/*`; 003 may do the same, optional).
- **Citation numbering** is by first use across sentences, conflicts, notices, bulletins,
  restricted and suggestion, so the same passage always has the same number on one screen.
- **Drafts are created on tap.** "Draft a work order" calls `POST /api/work-orders` immediately
  (state `draft`, nothing external), so `approval_reasons` and `target_system` come from the server.
  Edits are saved with `PATCH` before request-approval or submit.
- **Who must approve** comes from the draft's `eligible_approvers` (user IDs), shown as names when
  the development user list is available and as IDs otherwise. The approve/reject buttons appear
  only for users in that list. The approver's note is sent as `note` and shown from
  `decision_note` on approved and rejected drafts.
- **Group words** (for "missing groups explained in plain words") come from `GET /api/groups`,
  loaded once per session; a client-side copy of the `users.json` descriptions (`GROUP_WORDS`) is
  only an offline fallback, and unknown groups show their ID.
- **Development sign-in list** comes from `GET /api/dev/users` (development only, `404` in
  production). Without it the sign-in screen falls back to a user ID field.
- **Suggestions without a machine** (`asset_id: null`) open a "New work order" screen that asks
  for the asset ID and sends it as top-level `asset_id` on `POST /api/work-orders`. Errors about
  the machine stay on that field; other errors are a form message.
- **Follow-ups** (answer.md, `AskRequest.previous`): the answer on screen is sent as `previous`
  (`answer_id`, `question_used` or the asked text, `asset.asset_id`). A "New question" button
  above the composer drops it; sign-out and reload drop it too, because answers are only in memory.
  When `question_used` differs from what was typed, "Answering: …" shows how the follow-up was read.
  Clarify options with `question` ("did you mean") resend that text; options with `asset_id` resend
  the question with `asset_id` and `clarification_of`. Both keep the clarify's own `previous`.
- **Abstain notices**: the engine marks every abstain notice `not_visible`, so on an abstain whose
  reason isn't `not_visible` the notice is titled "Why there's no answer", not "Not visible to you".
- **Errors** follow http-api.md "Errors": `{"error", "detail"?}` with the listed codes.

## Running

```bash
uv run python web/dev/mock_api.py            # http://localhost:8000/
node --test web/tests/*.test.mjs
uv run python -m unittest web/dev/test_mock_api.py
node web/dev/screenshots.mjs                 # needs the mock running and Google Chrome installed
```

React client, during the migration (two terminals):

```bash
uv run python web/dev/mock_api.py                     # API on :8000
cd web-react && npm install && npm run dev            # http://localhost:5173/, /api proxied to :8000
npm run build && uv run python web/dev/mock_api.py --web web-react/dist   # built client on :8000
node web/dev/screenshots.mjs                          # walkthrough against the built client
```

Mock keywords: "E-31" → restricted for users missing cert-hv (high-voltage certification) or
family-compressors (Vastra VRS compressor training), listing whichever they lack (without a TAC-C
asset ID in the question, no machine is resolved and the suggestion has `asset_id: null`), and a
short answer for users with both; "BX-20" → abstain; "Fresno" without an FRS-P asset ID → clarify;
"HCP-200" → unverified; "oil" or "VRS-75" → mock-only answer with steps and an undecided conflict;
"HCP-20" (one character off a known model) → "Did you mean HCP-200?" clarify, and "clearance" on the
HCP-200 → a translated-scan answer; follow-ups starting "oh", "and", "also", "what about", "how
about", "I meant" or "sorry" are rewritten against `previous` and return `question_used`; "slow" waits 8 s; "fail" → 503 model_unavailable; anything else → answer.json (q04, casing torque).
Passage p_0ee8e5f1561408d13db4a416 (VRS-75 manual Rev B, before maintenance) always answers 403.

## Migration to React

**Rule**: the React client replaces the plain one only when it passes every check the plain one
passes today. The walkthrough, the mock tests and the spec's requirements are the bar; nothing in
`specs/contracts/` changes except where the build output is served from.

**What carries over unchanged**: the mock API and fixtures, `test_mock_api.py`, the 375 px
walkthrough checks (console errors, horizontal overflow, tap targets under 44 px, stray `null` or
`undefined`, the withheld HCP-200 (1998 pump manual, German scan) rated-head value on screen,
nothing in `localStorage`), the hash routes, and every rendering rule in "Design decisions".

**Rules specific to React**:
- Answer and source text is rendered only as React text children. `dangerouslySetInnerHTML` is
  banned by lint (`react/no-danger`), and the AI Elements markdown renderer (Streamdown) is never
  given answer or source text: unverified segments and `[[unverified:…]]` markers must go through
  `lib/text.ts` exactly as today (FR-002: withheld values never displayed).
- AI Elements components expect the Vercel AI SDK's streaming chat messages. Our API returns one
  `AnswerResponse` per question, so the components are used for layout only and are filled from
  `AnswerResponse` fields; the `ai` package is a type-only dependency at most, and `useChat` is not
  used.
- TanStack Query: no persister, `retry` only on network errors and `503`, never on `401`, `403`,
  `404` or `422`; cancelling the pending question aborts the request.
- The source viewer and the draft open as Vaul bottom sheets on top of the answer, and each also has
  its own hash route so a citation link still opens on its own.

**Contract change needed**: `specs/contracts/http-api.md` ("Static files and client routes") says
003 serves `web/` with `/styles.css` and `/js/*.js`. The Vite build writes `index.html` plus hashed
files under `/assets/`. Proposed wording: 003 serves `web/dist/` at `/`, with correct
`Content-Type` for `.js` and `.css` under `/assets/`, `index.html` for `/`, `/sources/*` and
`/work-orders/*`, and nothing outside `web/dist/`. Per `specs/coordination/README.md` rule 5 this is
made by the orchestrator after a `REQUEST` and a `DECISION`; 003 is not built yet, so nothing
depends on the old wording.

**As built (2026-10-13, before cutover)**:
- First load is about 126 KB gzip in 6 files, and the first screen appears in 1,877 ms under the
  Chrome DevTools "Slow 4G" preset (562.5 ms latency, 1.44 Mbit/s). To get there, a small inline
  script in `index.html` starts `/api/session` and `/api/dev/users` while the bundle downloads,
  and Sonner (toasts) loads after the first screen. A Content-Security-Policy added later would
  need that script's hash.
- The source viewer, pinch-zoom and draft form are separate lazy chunks.
- The plain client takes 3,055 ms on the same check: its ES modules load as a chain of requests.
- AI Elements are trimmed: no Streamdown, `motion`, `use-stick-to-bottom` or hover cards.
  `Conversation` doesn't stick to the bottom, because an answer must be read from the top.
- Tooling deviations:
  - ESLint 9, because `eslint-plugin-react` doesn't support ESLint 10.
  - TypeScript 6.0, because typescript-eslint needs a version below 6.1.
  - Installing needs npm 11 (`npx -y npm@11 ci --ignore-scripts`), because npm 10.9.2 crashes
    while resolving Vitest's peer dependencies.
- The walkthrough's synthetic `input` events now bubble, as real typing does, because React
  listens at the root.

**Cutover**: when T033–T046 are done, `web-react/` becomes `web/`, the plain client's `index.html`,
`styles.css`, `js/` and `tests/` are deleted, the mock serves `web/dist/`, and the walkthrough
screenshots are regenerated.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Principle VIII (simplest architecture): a UI framework (React) and a build step (Vite, npm) in a client that currently has neither | Owner decision 2026-10-12 to raise the client's visual quality and phone interaction: bottom sheets for sources and drafts, pinch-zoom on scanned pages, accessible dialogs and popovers, and polished chat, citation and confirmation components (shadcn/ui, Radix, AI Elements) that exist only for React. Hand-building these to the same accessibility standard would cost more than adopting them. | Keeping the plain client and hand-writing these components: each (focus trapping, drag-to-dismiss sheets, pinch-zoom, popover positioning) is a project of its own and would be less tested than Radix and Vaul. Preact with `preact/compat`: smaller, but shadcn/ui, Radix and AI Elements target React and compatibility gaps would cost more than the bytes saved. The cost of the build step is contained: the output is static files served by 003, with no new service, no server-side rendering and no service worker. SC-004 (success criterion: first screen under 2 s on a slow connection) is protected by the 170 KB gzip budget, which the walkthrough checks. |
