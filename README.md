# Field Service Copilot: Handy Manual

A phone assistant for Corvane's field technicians. A technician asks a question at the machine
and gets a short answer with numbered steps, where every sentence cites a passage they are
allowed to read and can open on the phone. Restricted procedures stay closed to technicians
without the certification, sources that disagree are shown side by side, and when no permitted
source covers the question the assistant says so instead of guessing. From an answer, the
technician can draft a work order that a lead approves before it goes to the maintenance system.

## Results

Latest evaluation (`specs/006-evaluation-harness/eval-fresh-20261014-1752.md`), over the 10
expert questions in `eval/questions.json` plus 22 restricted-procedure and adversarial questions.
It was a fresh run: every answer was written by the model, none came from the model cache.

| Check | Result |
|---|---|
| Correct outcome (answer, restricted, abstain, clarify) | 10/10 golden, 22/22 restricted and adversarial |
| Restricted content disclosed to an uncertified user | 0 |
| Citations re-opened as the asking user | 242 opened, 0 failures |
| Access grid (every user against every passage) | pass |
| Expert key facts present in the answers | 73 of 85 (4 of 10 answers complete) |
| Latency per answer | median 5.3 s, max 13.7 s |
| Model cost | US$0.42 for 30 answers (about US$0.014 each) |

The missing facts are omissions, not wrong statements; they are listed per question in the report
and under Known limitations below. The earlier cached run
(`specs/006-evaluation-harness/eval-20261014-1151.md`) had 74 of 85; the facts that are missed
change a little from run to run, but the outcomes and the access checks do not.

## How it works

Six packages, each built from a spec in `specs/` (spec, plan and tasks per feature):

| Feature | Package | What it does |
|---|---|---|
| 001 corpus ingestion | `src/copilot_ingest` | Extracts the 42 files (PDF with OCR, DOCX, HTML, mail, chat, CSV exports), joins access rules, links assets, bulletins and service history across the two maintenance systems, embeds passages, and publishes a versioned dataset (`ds_NNNN`) after validation |
| 002 answer engine | `src/copilot_answer` | A fixed pipeline: resolve the machine, retrieve only passages the user may see, decide applicability and conflicts in code, write the answer with a fast model, then validate every citation and value |
| 003 answer API | `src/copilot_api` | One FastAPI process: cookie session, answers, source viewer, work orders, audit, and the built web client |
| 004 mobile web client | `web-react/` | The React phone client (375 px), served by the API from `web-react/dist` |
| 005 work-order drafts | `src/copilot_workorders` | Drafts, approval by an eligible lead, and an outbox to MaintPro (North America) or Servio (Europe) |
| 006 evaluation harness | `src/copilot_eval` | Asks every question as its user over HTTP, scores outcomes and key facts, re-opens every citation, checks for disclosures, and runs the full access grid |

Shared types and the HTTP contract are in `src/copilot_contracts` and `specs/contracts/`. The
rules every feature follows are in `.specify/memory/constitution.md`; the main ones:

- Access is enforced in the retrieval query, outside the model. The model only ever sees text
  the asking user may read, and access fails closed.
- Every sentence cites a passage, and code checks that each value in the sentence is in that
  passage before the answer is returned.
- Which revision, serial range or bulletin applies is decided by code, not the model.
- The assistant drafts work orders; people approve and submit them.

The agents that built each feature coordinated through the files in `specs/coordination/`;
those hold every decision and report.

## Running it

All commands run from the repository root. Ports: the app on 8000, the evaluation harness on
8020 (it starts its own server).

### 1. Prerequisites (macOS with Homebrew)

```bash
brew install uv postgresql@17 pgvector tesseract tesseract-lang node
brew services start postgresql@17
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
createdb copilot
tesseract --list-langs | grep deu      # German OCR data must be listed
```

Python 3.12 is installed by `uv` on first use. Google Chrome is needed only for the scripted
walkthrough.

### 2. Configure

```bash
uv sync
cp .env.example .env
```

Then set `OPENAI_API_KEY` in `.env`. The other values in `.env.example` are the ones used for
the results above:

| Variable | Used for |
|---|---|
| `LLM_MODEL_FAST` (`gpt-5.4-mini-2026-03-17`) | every answer-engine call, and translation and metadata checks in ingestion |
| `LLM_MODEL_STRONG`, `VISION_MODEL` (`gpt-5.5-2026-04-23`) | ingestion only: reading scanned pages |
| `EMBEDDING_MODEL` (`text-embedding-3-large`, 1024 dims) | passage and question embeddings |
| `DATABASE_URL` | Postgres (`postgresql:///copilot`) |

Optional: `SESSION_SECRET` keeps sign-ins across server restarts; `APP_ENV=production` refuses to
start without it.

### 3. Build the dataset

```bash
uv run copilot-ingest db init    # control and cache schemas, pgvector; safe to rerun
uv run copilot-ingest run        # extract, link, embed, validate, publish ds_NNNN
uv run copilot-ingest status     # the published version
uv run copilot-ingest report     # each of the 42 files' outcome, review items, validation
```

The first run makes model calls (OCR of the scans with the larger model, translation, bulletin
conditions, embeddings; about US$0.50) and takes a few minutes. Every model call is cached in
Postgres by model, prompt version and input, so later runs only redo changed files. To rebuild and
validate without changing the version the app serves:

```bash
uv run copilot-ingest run --no-publish
```

`--offline` uses cached model calls only; any call missing from the cache is skipped and
reported, so validation can fail where a normal run passes.

Expected outcomes (quarantined files, duplicates, bulletin links, review items) are listed in
`specs/001-corpus-ingestion-pipeline/quickstart.md`.

### 4. Run the app

```bash
cd web-react && npm ci && npm run build && cd ..
WEB_DIR=web-react/dist uv run python -m copilot_api --port 8000
```

Open http://localhost:8000 (or on a phone on the same network, with `--host 0.0.0.0`). Sign-in is
a development user picker: choose a test user from `users.json`. Questions that show each
behaviour:

| User | Question | Expected |
|---|---|---|
| u01 (pump technician, North America) | HCP-500 is showing P-07. What does that mean and what should I check first? | an answer with numbered steps, every sentence cited |
| u02 (compressor technician, high-voltage certified) | TAC-C-0143 tripped on E-31. How do I reset it? | the reset steps |
| u03 (compressor technician, not high-voltage certified) | TAC-C-0143 tripped on E-31. How do I reset it? | "certification required", no steps, an offer to draft a work order |
| u04 (pump and conveyor technician) | What torque do I use on the casing bolts for FRS-P-0031 after a seal change? | the value for this pump's serial range, and why the older manual's 45 N-m doesn't apply |
| u03 | TAC-C-0142 tripped E-14 again. Has this happened before and what fixed it? | the machine's service history across both maintenance systems |
| u05 (chiller engineer, refrigerant certified) | RTM-H-0007 has an L-03 alarm again, suction at 1.9 bar. What should I do? | check the expansion valve first, per the campaign bulletin |
| u12 (conveyor technician) | What's the warranty period on a Belton BX-20? | no permitted source covers it, and the assistant says so |

Tap any citation to open its passage. From an answer, "Draft work order" creates a draft; drafts
that need parts or a certification are approved by a lead (u07 for EU compressors, u08 for North
American pumps and compressors) before they go to the outbox.

From the command line instead of the app:

```bash
uv run python -m copilot_answer ask --user u03 "TAC-C-0143 tripped on E-31. How do I reset it?"
```

It prints the answer as JSON and its cost.

### 5. Evaluate

```bash
uv run python -m copilot_eval run --budget 1.00            # uses cached model calls where it can
uv run python -m copilot_eval run --fresh --budget 1.00    # every answer written anew
```

The harness starts its own API on port 8020, asks the 10 expert questions and 22 restricted and
adversarial questions as their users, re-opens every citation, checks for disclosures and runs
the access grid (every user against every passage). A fresh run takes about 10 minutes and costs
about US$0.45. The verdict is printed, the exit code is 0 on a pass, and the report goes to
`data/reports/`.

### 6. Tests

```bash
uv run ruff check src tests
uv run pytest -m "not hosted"                           # offline, about 2 minutes
uv run pytest -m hosted tests/answer/test_golden.py     # golden questions, makes model calls
cd web-react && npm test && npm run lint && cd ..
```

The client walkthrough drives headless Chrome through every screen at 375 px and fails on layout,
contrast, tap-target or console problems. Against the mock server, which needs no model calls:

```bash
uv run python web-react/dev/mock_api.py --port 8031 --web web-react/dist &
node web-react/dev/screenshots.mjs --base http://localhost:8031 --out /tmp/screens --theme light
```

Against the real API, with the same checks adapted to real answers. Work orders go to a
temporary schema that is dropped when the server stops; uncached answers make model calls:

```bash
WEB_DIR=web-react/dist uv run python tests/api/serve_scratch.py --port 8010 &
node web-react/dev/screenshots_real.mjs --base http://localhost:8010 --out /tmp/screens-real
```

Stop each background server with `kill %1` afterwards. The screenshots from the last real-API run
are in `specs/004-mobile-web-client/screenshots-react-real/`.

## Known limitations

- **Development sign-in.** Anyone can sign in as any test user. Hiding the user list in production
  is open (T023 in `specs/004-mobile-web-client/tasks.md`).
- **Incomplete answers.** 12 of 85 expert key facts are missing in the fresh run, in q04, q05,
  q06, q08, q09 and q10.
  Most are details the model had in its evidence and left out, such as an escalation branch or a
  case number; q06 also leaves out facts an uncertified technician may see, because the
  restricted-procedure rule takes priority. A stronger model for the writing step or a
  completeness pass are the next steps; neither has been tried.
- **The fact checker is literal.** It matches values and identifiers, not meaning, so some
  correct rewordings count as misses.
- **Search ordering.** The published dataset ds_0028 still has the old tie order in identifier
  search; the engine works around it until the next publish (T100 in
  `specs/001-corpus-ingestion-pipeline/tasks.md`).
- **Mentioned assets.** A case or record is tagged with every machine it mentions, not only its
  subject (T101).
- **No EU approver for conveyor parts.** In the test users, the only EU lead, u07, covers
  compressors, so an EU conveyor draft that orders parts can't be approved. The approval rules
  are working as specified; the test users don't include that lead.
- **No approval inbox in the client.** A lead opens a pending draft from its link
  (`#/work-orders/<draft id>`); the API lists a lead's pending drafts, but the client has no
  screen for them yet.

## Demo videos

In `demos/`: `handy-manual-demo.mp4` (product walkthrough on a phone, with real answers from
the API), `handy-manual-design.mp4`
(the three UI directions) and `handy-manual-engineering.mp4` (the system design). Each is built
by the `make_*_video.py` script next to it:
`uv run --with pillow python demos/make_demo_video.py`, which also needs ffmpeg.

## The customer data

This is a document export from a fictional customer, Corvane Field Services. Corvane services pumps, compressors, chillers and conveyors at four customer sites in North America and Europe. In 2024 it bought a Dutch service company, Kyltek, and the integration isn't finished.

- `corpus/`: 42 files exported from Corvane's systems: manufacturer manuals and service bulletins (PDF), controlled procedures and work instructions (SharePoint, DOCX), the field wiki (Confluence HTML export), emails, a Teams channel export, maintenance-system exports from two different systems, Salesforce case exports, and an ops review. It's a real-world export, so expect some mess.
- `users.json`: the technicians, their groups, and what each group means.
- `permissions.json`: for each document, the groups a user needs. A user may see a document only if they belong to every group in `required_groups`. An empty list means every technician may see it.
- `eval/questions.json`: 10 questions, each asked by a specific user, with a reference answer from Corvane's experts.
