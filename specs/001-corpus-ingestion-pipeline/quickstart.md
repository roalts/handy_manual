# Quickstart: Corpus Ingestion Pipeline

How to run the pipeline and prove it meets the spec. Commands are in
[contracts/cli.md](./contracts/cli.md); tables in [data-model.md](./data-model.md).

## Prerequisites

- Postgres 17 running locally with pgvector: `brew services start postgresql@17`; database
  `copilot` exists.
- `export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"`
- Tesseract with German data: `tesseract --list-langs` includes `deu`.
- uv installed. On this machine `~/.local` is root-owned, so set
  `UV_PYTHON_INSTALL_DIR="$HOME/Library/Application Support/uv/python"` before `uv sync`.
- `.env` with `OPENAI_API_KEY`, `DATABASE_URL=postgresql:///copilot`, `CORPUS_DIR=corpus`,
  `DATA_DIR=data`.

## Run

```bash
uv sync
uv run copilot-ingest db init
uv run copilot-ingest run
uv run copilot-ingest report
```

## Expected outcomes on the current corpus

| Check | Expected |
|---|---|
| Files in report | 42, each with exactly one outcome |
| Quarantined | `VRS-110-VFD-quick-reset-unofficial.html` (no_access_rule), `Inspection_Checklist_Q3_FINAL.docx` (empty_file) |
| Partial | `Vastra_SB-2026-015_VRS-45_Coupling.pdf`, missing pages listed |
| Duplicates | `NK600_manual_final_v2.pdf` collapsed into Nordkyl NK-600 Rev C, two origins |
| Supersession | VRS-75 Rev C supersedes Rev B |
| Bulletin links | FRS-P-0031 affected by SB-2025-009; RTM-H-0007 in campaign NK-C25-14; TAC-C-0142 affected by SB-2026-003 |
| Aliases | `MFL-KM07` resolves to `RTM-H-0007` |
| Dates | Servio `02-12-2025` stored as 2025-12-02 |
| History | TAC-C-0142 E-14 events in 2026-03 and 2026-07, linked to cases 00041207 and 00042388, each once |
| Scan | HCP-200 clearance shown as a withheld marker until reviewed, or 0.38-0.50 mm if both passes agree |
| Restricted | No passage visible to u03 contains `P9.01` or `TP1`; Compressor Playbook E-31 section and Work Order Writing Guide remain visible to u03 |
| Validation | all checks pass; `ds_0001` published |

## Validate

```bash
uv run pytest tests/acceptance tests/acl     # spec facts and the 12 x 42 visibility grid
uv run copilot-ingest visible --user u03 --search "E-31 reset"
uv run copilot-ingest review list --kind ocr_value_mismatch
```

Resolve the clearance after reading page 3 of the scan, then re-run:

```bash
uv run copilot-ingest review show <item_id>
uv run copilot-ingest review resolve <item_id> --value '"0,38 - 0,50 mm"' --note "read from scan"
uv run copilot-ingest run      # marker replaced, value marked reviewer_verified
```

## Incremental and safety scenarios

1. Re-run with no changes: report shows 0 passages changed (SC-005).
2. Edit one wiki page, re-run with `--only <path>`: only its passages change; published within
   5 minutes (SC-006).
3. Delete a file, re-run: none of its passages or events are visible to anyone (SC-007).
4. Tighten an access rule in `permissions.json`, re-run: affected users lose visibility.
5. Remove a document's access rule, re-run: it is quarantined and invisible.
6. Break an acceptance fact on purpose (for example, edit `acceptance/ingestion_facts.yaml` to
   expect a wrong alias), run: exit code 2, previous version still published (`copilot-ingest
   status`).
