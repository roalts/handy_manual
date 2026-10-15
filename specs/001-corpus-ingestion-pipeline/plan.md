# Implementation Plan: Corpus Ingestion Pipeline

**Branch**: `001-corpus-ingestion-pipeline` | **Date**: 2026-10-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-corpus-ingestion-pipeline/spec.md`

## Summary

Build a command-line ingestion pipeline that turns Corvane's 42 exported files (and future files
in the same formats) into a validated, versioned dataset in local Postgres: authorized and
traceable passages, a machine registry with one merged service history per machine, and
applicability, revision, and authority metadata. The pipeline runs in eight stages (register,
extract, normalize, enrich, link, chunk, index, validate) with per-stage artifacts on disk,
fail-closed access control, two-pass OCR with value cross-checking, quote-verified LLM extraction,
and atomic publishing of a new dataset version only after acceptance checks pass. The query
feature reads the dataset through a fixed serving contract.

## Technical Context

**Language/Version**: Python 3.12 (managed with uv)

**Primary Dependencies**: PyMuPDF and pikepdf (PDF extraction and repair), python-docx, BeautifulSoup
with lxml, Python `email`, pandas (tabular exports), Tesseract 5 CLI with deu/nld/swe/eng data,
OpenAI SDK (vision OCR, translation, metadata extraction, embeddings; behind a provider adapter),
lingua-language-detector, tiktoken, rapidfuzz, Pydantic v2, Typer, psycopg 3, pgvector-python

**Storage**: PostgreSQL 17 with pgvector 0.8 (local Homebrew service, database `copilot`); stage
artifacts, page images, and immutable raw copies on local disk under `data/`

**Testing**: pytest (unit per stage, integration on the real corpus, acceptance facts from the
spec, full access-control grid of 12 users x 42 documents)

**Target Platform**: macOS (Apple Silicon) developer machine; Linux-compatible

**Project Type**: CLI pipeline plus a read contract (Postgres views and functions) for the query
feature

**Performance Goals**: full ingestion of the current corpus and publish in under 30 minutes;
single-document update published in under 5 minutes (SC-006)

**Constraints**: fail-closed access control; deterministic output for identical input; no
unverified OCR value in retrievable text; every automated metadata value backed by a verified
quotation; hosted model calls cached by content hash

**Scale/Scope**: 42 source files, about 2,000-3,000 passages, 30 machines, about 1,100 service
records, 12 users, 12 groups; designed so the same schema holds at production scale

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | How this plan complies | Status |
|---|---|---|
| I. Authorization outside the model | Access rules attached from the authoritative file at registration; missing rule means quarantine; effective rules only ever tightened; visibility enforced by a database function that returns nothing for rows without access alternatives (fail closed by construction); LLMs never set access rules | Pass |
| II. Grounded and verifiable | Every passage stores document, location, fingerprint, processing version; page images kept for scans; disputed OCR values withheld behind a marker | Pass |
| III. Abstain rather than guess | Applicability has an explicit "check on site" outcome instead of guessing; unextractable applicability left empty and sent to review, never assumed to cover all units | Pass |
| IV. Applicability and authority by code | Bulletin rules parsed into structured rows and evaluated by code against the fleet register; authority tier derived from document type by rule; supersession recorded; conflicts retained, not resolved | Pass |
| V. Restricted procedures as safety controls | Restricted-content tagging from markers derived from controlled procedures plus similarity to their steps; tagging only adds groups; uncertain matches restricted until reviewed | Pass |
| VI. Assistant drafts, humans commit | Not applicable to ingestion (no external writes) | N/A |
| VII. Measured before shipped | Publish gated on validation: acceptance facts, access-control grid, fail-closed checks, coverage checks | Pass |
| VIII. Simplest architecture | One CLI, one database, no orchestration server, no vector DB, no agent framework; LLMs used only for OCR cross-check, translation, and quote-verified extraction | Pass |
| Corpus and ingestion constraints | Incremental by fingerprint, deletions propagate, provenance per passage, OCR plus translation with originals kept, duplicates and revisions linked, both maintenance systems normalized | Pass |

**Post-design re-check (after Phase 1)**: Pass. The data model's access alternatives make
duplicate documents visible to a user permitted any origin without loosening any single rule; the
serving contract exposes only rows that pass the visibility function. No violations; Complexity
Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-corpus-ingestion-pipeline/
├── plan.md              # This file
├── research.md          # Phase 0: decisions and rationale
├── data-model.md        # Phase 1: schemas, relations, state transitions
├── quickstart.md        # Phase 1: how to run and validate
├── contracts/
│   ├── cli.md           # Operator commands, options, exit codes, outputs
│   └── serving.md       # What the query feature may read, and the guarantees
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (/speckit-tasks; not created here)
```

### Source Code (repository root)

```text
pyproject.toml
.env.example                     # OPENAI_API_KEY, DATABASE_URL, CORPUS_DIR, DATA_DIR
config/
├── sources.yaml                 # per-source conventions: delimiter, date format, decimals, lang
├── authority.yaml               # document type -> authority tier, controlled flags
├── identifiers.yaml             # ID patterns: assets, serials, cases, parts, fault codes, models
├── glossary_nl_de_sv.yaml       # domain terms for consistent translation (storing -> fault)
└── restricted_markers.yaml      # reviewed markers per restricted procedure (generated, approved)
src/copilot_ingest/
├── cli.py                       # Typer entry point (see contracts/cli.md)
├── settings.py
├── models.py                    # Pydantic: SourceFile, Block, Passage, Asset, ServiceEvent, ...
├── ids.py                       # deterministic IDs and fingerprints
├── db/
│   ├── migrations/              # control, cache, dataset-version, and serving schemas
│   └── repo.py
├── providers/
│   ├── base.py                  # LLM, vision, embedding interfaces
│   ├── openai_provider.py
│   └── cache.py                 # content-hash keyed call cache
├── stages/
│   ├── register.py              # fingerprint, ACL join, quarantine
│   ├── extract/
│   │   ├── pdf_text.py          # native PDFs, email printed to PDF
│   │   ├── pdf_repair.py        # damaged PDFs
│   │   ├── pdf_scan.py          # page images, Tesseract + vision, value cross-check
│   │   ├── docx.py
│   │   ├── confluence_html.py
│   │   ├── eml.py
│   │   ├── teams_json.py
│   │   ├── salesforce_json.py
│   │   └── tabular.py           # fleet register, MaintPro, Servio
│   ├── normalize.py             # dates, numbers, identifiers, aliases, status, language
│   ├── translate.py
│   ├── enrich.py                # doc metadata, bulletin rules, passage identifiers
│   ├── restricted.py            # marker generation and restricted-content tagging
│   ├── link.py                  # duplicates, supersession, staleness, bulletin->asset, event merge
│   ├── chunk.py                 # structure-aware passages, parent/child procedures
│   ├── index.py                 # embeddings, build dataset version schema
│   ├── validate.py              # acceptance facts, ACL grid, coverage checks
│   ├── publish.py               # atomic switch of serving views
│   └── report.py
└── review.py                    # review queue operations
acceptance/
└── ingestion_facts.yaml         # spec acceptance facts as machine-checkable assertions
tests/
├── unit/                        # per-stage logic on small fixtures
├── integration/                 # each extractor on the real corpus file(s)
├── acceptance/                  # runs ingestion_facts.yaml against a built version
└── acl/                         # 12 users x 42 documents visibility grid
data/                            # gitignored
├── raw/                         # immutable copies named by fingerprint
├── artifacts/<fingerprint>/     # per-stage JSON outputs, keyed by stage version
├── page_images/<fingerprint>/   # rendered scan pages (TIFF for OCR, PNG for viewing)
└── reports/<run_id>/            # run report (Markdown and JSON)
```

**Structure Decision**: a single Python package with one module per pipeline stage and one
extractor per source format. Stage outputs are files on disk so any stage can be re-run and
inspected in isolation; the database holds the control state (runs, source files, review queue),
caches, dataset versions, and the serving schema the query feature reads.

## Phase Outline

- **Phase 0 (research.md)**: resolved decisions for storage layout, versioning and atomic publish,
  access representation, OCR cross-check, quote verification, bulletin applicability, restricted
  tagging, translation, chunking, embeddings, provider choice, incremental processing.
- **Phase 1 (data-model.md, contracts/, quickstart.md)**: schemas and state transitions; operator
  CLI and serving contracts; runnable validation guide.
- **Phase 2 (/speckit-tasks)**: task breakdown ordered by the spec's story priorities, with the
  acceptance facts and the ACL grid as the first tests written.

## Risks

| Risk | Evidence | Mitigation |
|---|---|---|
| OCR misreads safety values | Tesseract read the HCP-200 clearance "0,38" as "2.10" | Two-pass cross-check; disputed values withheld (FR-024); reviewer confirmation path |
| Bulletin applicability needs facts not in the fleet register | SB-2025-009 "V2 cover" condition; SB-2025-014 market condition | Three-valued outcome (affected, not affected, check on site); conditions stored verbatim with quotes |
| Restricted tagging over-tags references | Work Order Writing Guide and Compressor Playbook mention E-31 and HV-PROC-07 without steps | Markers built from step content (parameters, test points, values), not document names; acceptance fact that those passages stay visible to u03 |
| Hosted provider unavailable or slow | Network or quota | Content-hash cache; stages resumable; provider adapter |
| Leptonica cannot read PNG on this machine | Observed in setup | OCR input rendered as TIFF |
| Site names differ across systems | Servio "Rotterdam DC Maasvlakte" vs fleet "Rotterdam Distribution Hub" | Site resolved via asset ID prefix and a site alias table |

## Complexity Tracking

No constitution violations to justify.
