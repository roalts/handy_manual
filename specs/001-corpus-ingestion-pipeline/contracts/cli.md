# Contract: Operator CLI (`copilot-ingest`)

All commands read settings from `.env` (`DATABASE_URL`, `CORPUS_DIR`, `DATA_DIR`,
`OPENAI_API_KEY`). Output is human-readable by default; `--json` gives machine-readable output.

## `copilot-ingest db init`
Creates `control`, `cache`, and `serving` schemas and the pgvector extension. Idempotent.
Exit 0 on success.

## `copilot-ingest run`
Runs all stages, builds a new dataset version, validates it, and publishes it if validation passes.

| Option | Meaning |
|---|---|
| `--corpus PATH` | Corpus root (default `CORPUS_DIR`) |
| `--acl PATH` | Access rules file (default `<corpus>/../permissions.json`) |
| `--users PATH` | Users and groups file (default `<corpus>/../users.json`) |
| `--only PATH ...` | Re-extract these files ignoring the cache; all other files reuse cached extraction. The result is a complete dataset and publishes normally |
| `--from-stage extract` | Re-extract every file (or every `--only` file) ignoring the cache. Only extraction is cached; every later stage reruns on each build |
| `--no-publish` | Build and validate only |
| `--offline` | Use cached model calls only; fail if a call is missing |

Exit codes: `0` published; `2` built but validation failed (previous version stays published);
`3` built with `--no-publish` (`--only` runs publish like full runs); `1` error before a version was built.

Stdout summary:
```text
run 20261012-031500  dataset ds_0003
files: 42  indexed: 39  partial: 1  quarantined: 2
passages: 2,614  events: 1,071  assets: 30  bulletin links: 118
review items: 6 open (1 ocr_value_mismatch, 4 metadata_unverified, 1 marker_approval)
validation: 57/57 passed
published: ds_0003   report: data/reports/20261012-031500/report.md
```

## `copilot-ingest report [--run RUN_ID] [--json]`
Prints the run report: every source file with exactly one outcome and reason; counts; OCR pages
and values verified or withheld; metadata gaps; review items; validation results.

## `copilot-ingest review list [--kind KIND] [--status open|resolved|obsolete]`
## `copilot-ingest review show ITEM_ID`
Shows source location, candidates, reason, and for OCR items the page image path.
## `copilot-ingest review resolve ITEM_ID --value VALUE [--note TEXT]`
Records a resolution; applied on the next `run`. `--value` is JSON or a plain string.

## `copilot-ingest status`
Published version, publish time, run ID, and the last 3 versions available for rollback.

## `copilot-ingest rollback VERSION`
Points `serving` at a retained earlier version.

## `copilot-ingest visible --user USER_ID [--doc PATH] [--search TEXT]`
Debug helper: lists documents or passages visible to a user via the serving contract.
