---

description: "Task list for the corpus ingestion pipeline"
---

# Tasks: Corpus Ingestion Pipeline

**Input**: Design documents from `specs/001-corpus-ingestion-pipeline/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli.md,
contracts/serving.md, quickstart.md

**Tests**: Included. The constitution (Principle VII) makes acceptance facts, the access-control
grid, and fail-closed checks release-blocking, and FR-036 requires them before publishing.

**Organization**: Tasks are grouped by user story so each story can be implemented and tested
independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1-US6)

## Path Conventions

Single project: `src/copilot_ingest/`, `tests/`, `config/`, `acceptance/` at the repository root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [X] T001 Create the package layout from plan.md (src/copilot_ingest/ with db/, providers/, stages/, stages/extract/; tests/unit, tests/integration, tests/acceptance, tests/acl; config/; acceptance/) with empty `__init__.py` files
- [X] T002 Create pyproject.toml for Python 3.12 with dependencies pymupdf, pikepdf, python-docx, beautifulsoup4, lxml, pandas, pydantic>=2, typer, psycopg[binary]>=3, pgvector, openai, lingua-language-detector, tiktoken, rapidfuzz, python-dotenv, pyyaml; dev dependencies pytest, ruff; console script `copilot-ingest = copilot_ingest.cli:app`
- [X] T003 [P] Configure ruff and pytest (markers `integration`, `acceptance`, `acl`, `hosted` for tests that call the provider) in pyproject.toml
- [X] T004 [P] Implement settings loading from .env (OPENAI_API_KEY, DATABASE_URL, CORPUS_DIR, DATA_DIR, LLM_MODEL_FAST, LLM_MODEL_STRONG, VISION_MODEL, EMBEDDING_MODEL, EMBEDDING_DIMS with default 1024) in src/copilot_ingest/settings.py
- [X] T005 [P] Create config/identifiers.yaml with canonical patterns for asset IDs (`(FRS|TAC|RTM|GDN)-[A-Z]-\d{4}`), legacy IDs (`MFL-[A-Z]{2}\d{2}`, `BPF-[A-Z]{2}\d{2}`), serials (`(HCP|VRS|NK|BX)\d{2,3}-\d{6}`), case numbers (8 digits, with `SF ` prefix variant), part numbers (`\d{2}-\d{4}`), fault codes (`[EPLC]-\d{2}`), bulletin IDs (`SB-\d{4}-\d{3}`), and model codes (`HCP-\d{3}`, `VRS-\d{2,3}`, `NK-\d{3}`, `BX-\d{2}`)
- [X] T006 [P] Create config/sources.yaml with per-source conventions from research.md R10: maintpro (delimiter `,`, date `%m/%d/%Y`, decimal `.`, lang en), servio (delimiter `;`, date `%d-%m-%Y`, decimal `,`, lang nl, status map Gereed->completed, Open->open, Geannuleerd->cancelled), fleet_register (date `%m/%d/%Y`), salesforce (ISO 8601), teams (ISO 8601, HTML bodies)
- [X] T007 [P] Create config/authority.yaml mapping doc_type to authority_tier (controlled_procedure 1, work_instruction 1, bulletin 2, service_manual 3, wiki 4, email 5, chat 5, case_export 0, maintenance_export 0, fleet_register 0, report 0) and controlled-document title patterns (`SOP-`, `HV-PROC-`, `CS-PROC-`, `KT-WI-`, `FS-STD-`, `FS-REC-`)
- [X] T008 [P] Create config/glossary_nl_de_sv.yaml with domain terms (storing->fault, gereset->reset, gereed->completed, monteur->technician, Spaltmaß->clearance, Laufrad->impeller, Gehäuse->casing, Anzugsmoment->tightening torque)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T009 Write migration src/copilot_ingest/db/migrations/001_control.sql creating schema `control` with tables runs, source_files, quarantine, review_items, resolutions, published exactly as in data-model.md, including `source_files.status` in (`active`, `quarantined`, `partial`, `removed`), `quarantine.reason` in (`no_access_rule`, `unknown_group`, `empty_file`, `unreadable`, `unsupported_format`), `review_items.kind` in (`ocr_value_mismatch`, `metadata_unverified`, `restricted_borderline`, `marker_approval`, `unresolved_link`, `unknown_asset`), `review_items.status` in (`open`, `resolved`), `runs.outcome` in (`published`, `built`, `validation_failed`, `error`)
- [X] T010 Write migration src/copilot_ingest/db/migrations/002_cache.sql creating `CREATE EXTENSION IF NOT EXISTS vector`, schema `cache` with `model_calls(key text PK, provider, model, prompt_version, input_hash, output jsonb, created_at)` and `embeddings(text_hash, model, dims int, embedding vector(1024), PRIMARY KEY (text_hash, model))`
- [X] T011 Write src/copilot_ingest/db/dataset_schema.sql, a template that creates schema `ds_NNNN` with tables documents, document_origins, document_relations, bulletin_rules, bulletin_assets, passages, access_alternatives, assets, asset_aliases, site_aliases, service_events exactly as in data-model.md (passages.role in (`standard`, `parent`, `child`); passages.ocr in (`none`, `verified`, `has_withheld_values`); documents.status in (`active`, `superseded`, `partial`); bulletin_assets.status in (`affected`, `in_campaign`, `not_affected`, `check_on_site`); service_events.status in (`completed`, `open`, `cancelled`); access_alternatives.object_type in (`document`, `passage`, `event`)), with GIN indexes on passages identifier arrays and `tsv`
- [X] T012 Implement src/copilot_ingest/db/repo.py: connection from DATABASE_URL, migration runner (applies 001 and 002 once, tracked in `public.schema_migrations`), `create_dataset_version()` returning the next `ds_NNNN` and executing dataset_schema.sql into it
- [X] T013 Write src/copilot_ingest/db/serving.sql defining `serving.can_see(object_type, object_id, user_groups)` (true iff some access alternative has `required_groups <@ user_groups`; false when no alternatives), and `serving.passages_for`, `events_for`, `documents_for`, `keyword_search`, `vector_search`, `identifier_search` per contracts/serving.md, each filtering through `can_see` before ranking, parameterized by schema name so publish can point them at a version
- [X] T014 Implement src/copilot_ingest/stages/publish.py: in one transaction, recreate the serving functions and reference views (`serving.assets`, `asset_aliases`, `site_aliases`, `bulletin_rules`, `bulletin_assets`, `document_relations`) against the new `ds_NNNN`, update `control.published`; refuse to publish unless the run's validation passed
- [X] T015 [P] Implement Pydantic models SourceFile, Block (types heading, paragraph, list_item, procedure_step, table, record, message, warning), Anchor (page, page_end, section_path, table, record_id, message_id), Passage, Document, Asset, ServiceEvent, BulletinRule, ReviewItem, QuarantineRecord in src/copilot_ingest/models.py
- [X] T016 [P] Implement deterministic IDs in src/copilot_ingest/ids.py: file fingerprint (SHA-256 of bytes), canonical doc_id (hash of normalized full text), passage_id (hash of doc_id, anchor, normalized text), review item_id (hash of fingerprint, stage, anchor, field), text normalization (NFKC, casefold, whitespace collapse, de-hyphenation)
- [X] T017 [P] Implement the artifact store in src/copilot_ingest/artifacts.py: read and write `data/artifacts/<fingerprint>/<stage>@<stage_version>.json`; raw copy to `data/raw/<fingerprint><ext>`
- [X] T018 Implement the stage runner in src/copilot_ingest/pipeline.py: ordered stages, each declaring `name`, `version`, and dependencies; skips a file when its artifact exists for the same fingerprint, stage version, access rule, and dependency hashes; collects quarantine records and review items
- [X] T019 [P] Implement the provider interface (`complete_json(model, prompt, schema, prompt_version)`, `transcribe_image(model, image, prompt_version)`, `embed(texts)`) in src/copilot_ingest/providers/base.py
- [X] T020 Implement src/copilot_ingest/providers/openai_provider.py using the Responses API with strict JSON-schema output and no `temperature` parameter, image input for transcription, and the embeddings endpoint with `dimensions` from settings; retries with backoff on rate limits
- [X] T021 Implement src/copilot_ingest/providers/cache.py wrapping any provider: key = hash(provider, model, prompt_version, input_hash) in `cache.model_calls`; embeddings cached in `cache.embeddings`; `--offline` mode raises on a cache miss
- [X] T022 [P] Implement the review queue core in src/copilot_ingest/review.py: upsert review items by stable item_id (update `last_run`, reopen if the source changed), fetch resolutions for a stage
- [X] T023 [P] Implement access-rule and user loading in src/copilot_ingest/acl.py: parse permissions.json and users.json; validate group names against the defined groups; expose `required_groups(path)` returning None when absent
- [X] T024 Implement the validation framework in src/copilot_ingest/stages/validate.py: registry of named checks returning pass/fail with detail; loader for acceptance/ingestion_facts.yaml assertions (document metadata, relations, bulletin links, aliases, event queries, passage text contains/does not contain, visibility per user)
- [X] T025 Implement the run report skeleton in src/copilot_ingest/stages/report.py writing `data/reports/<run_id>/report.md` and `report.json` (files with outcome and reason, counts, validation results)
- [X] T026 Implement CLI commands `db init`, `run` (options per contracts/cli.md, exit codes 0/1/2/3), and `status` in src/copilot_ingest/cli.py
- [X] T027 [P] Write tests/unit/test_ids.py (determinism of fingerprints and passage IDs) and tests/unit/test_can_see.py (fail-closed: object without alternatives invisible; empty-group alternative visible to all; superset requirement)

**Checkpoint**: Foundation ready. `copilot-ingest db init` works; an empty run builds and publishes an empty validated version.

---

## Phase 3: User Story 1 - Authorized, traceable passages from text-based sources (Priority: P1) 🎯 MVP

**Goal**: Every text-based document becomes passages with correct effective access rules and exact
source locations; unsafe or broken inputs are quarantined; restricted steps are tagged.

**Independent Test**: Run ingestion; for each of the 12 users, visible passages match the access
rules; any passage's anchor opens the right location; the unofficial reset page and the empty
checklist are quarantined.

### Tests for User Story 1 ⚠️

> Write these first and confirm they fail before implementation.

- [X] T028 [P] [US1] Add US1 assertions to acceptance/ingestion_facts.yaml: unofficial quick-reset page quarantined `no_access_rule`; Inspection_Checklist_Q3_FINAL.docx quarantined `empty_file`; HV-PROC-07 steps in one parent passage; every table passage contains its header; Teams deleted message absent and edited message latest; no passage visible to u03 contains `P9.01` or `TP1`; Compressor Troubleshooting Playbook E-31 section and Work Order Writing Guide visible to u03
- [X] T029 [P] [US1] Write tests/acl/test_visibility_grid.py: for all 12 users x 41 documents with access rules, the set of visible documents and passages equals the expected set computed directly from permissions.json and users.json (SC-001); no quarantined path visible to any user
- [X] T030 [P] [US1] Write tests/unit/test_register.py: missing rule -> `no_access_rule`; unknown group -> `unknown_group`; zero bytes -> `empty_file`; unreadable -> `unreadable`
- [X] T031 [P] [US1] Write tests/unit/test_chunk.py: procedure never split without parent; over 800 tokens yields parent plus children of about three steps; table header repeated in every row group; heading_path attached; sections up to 500 tokens stay whole
- [X] T032 [P] [US1] Write tests/unit/test_restricted.py: a passage with two approved HV-PROC-07 markers gains `cert-hv` and `family-compressors`; a passage only naming "HV-PROC-07" gains nothing; tagging never removes groups; borderline similarity creates a `restricted_borderline` review item and is treated as restricted

### Implementation for User Story 1

- [X] T033 [US1] Implement src/copilot_ingest/stages/register.py: walk the corpus (ignore `.DS_Store`), fingerprint, copy raw, join access rules, detect added, changed, and removed files against `control.source_files`, quarantine per FR-003 with reasons from T009
- [X] T034 [P] [US1] Implement src/copilot_ingest/stages/extract/pdf.py: PyMuPDF block extraction with font size and bold for heading detection, table reconstruction, removal of repeated headers and footers, anchors with page numbers; ignore embedded PDF metadata for titles and dates; route pages with images and no text to the scan path
- [X] T035 [P] [US1] Implement src/copilot_ingest/stages/extract/docx.py: heading styles to section paths, numbered lists to procedure_step blocks, tables with header rows, detection of tracked changes (`w:ins`, `w:del`) and comments recorded as flags
- [X] T036 [P] [US1] Implement src/copilot_ingest/stages/extract/html.py: strip TOC and style macros, keep h1-h3 as headings, lists, tables, and Confluence warning and info boxes as `warning` blocks; anchors by section path
- [X] T037 [P] [US1] Implement src/copilot_ingest/stages/extract/messages.py: plain-text part preferred, HTML fallback; split thread into messages; remove quoted text only when the quoted message exists as its own message; strip signatures; record sender, recipients, date
- [X] T038 [P] [US1] Implement email-printed-to-PDF handling in src/copilot_ingest/stages/extract/messages.py (detect `From:`/`Sent:` header blocks, e.g. HCP-350_casing_leak_FRS-P-0031_Halden_thread.pdf) producing message blocks
- [X] T039 [P] [US1] Implement src/copilot_ingest/stages/extract/messages.py (Teams): rebuild threads via `replyToId`, drop messages with `deletedDateTime`, use latest edit, HTML to text, record attachment names; one record block per thread with message anchors
- [X] T040 [P] [US1] Implement src/copilot_ingest/stages/extract/messages.py (Salesforce): one record block per case including Subject, Description, Resolution__c, Fault_Code__c, Asset__r.Name, Serial_Number__c, CaseComments, EmailMessages; anchor `record_id` = CaseNumber
- [X] T041 [US1] Implement page and section coverage check in src/copilot_ingest/stages/extract/__init__.py (FR-008): every page or section has blocks or an explicit reason (`scanned`, `blank`, `figure_only`, `unrecoverable`)
- [X] T042 [US1] Implement identifier extraction for passages in src/copilot_ingest/stages/normalize.py using config/identifiers.yaml: canonical fault codes (`e-31` -> `E-31`), case numbers (`SF 00041876` -> `00041876`), part numbers, asset IDs, serials, model codes, keeping original text
- [X] T043 [US1] Implement src/copilot_ingest/stages/chunk.py per research.md R12 using tiktoken counts: section passages up to 500 tokens, procedures whole with parent/child above 800 tokens, tables with headers, one passage per case, maintenance record, chat thread, email message, sentence windows with 50-token overlap for unstructured prose
- [X] T044 [US1] Implement marker generation in src/copilot_ingest/stages/restricted.py: identify restricted procedures (controlled documents whose rule includes `cert-hv`, `cert-refrigerant`, or `cert-confined-space`); propose markers from their step passages that are rare elsewhere (parameters, test points, thresholds with actions; never document names); write proposals to a `marker_approval` review item and load approved markers from config/restricted_markers.yaml
- [X] T045 [US1] Implement restricted-content tagging in src/copilot_ingest/stages/restricted.py: tag passages outside the procedure with two or more approved markers or embedding similarity above the calibrated threshold to any step passage; add the procedure's groups to every access alternative; borderline -> `restricted_borderline` review item, restricted until resolved
- [X] T046 [US1] Implement src/copilot_ingest/stages/index.py for passages: compute effective access alternatives (document origin rules plus restricted groups), build `tsv` with the `simple` configuration over text_en and text_original, embed `heading_path + text` through the cached provider, insert documents, document_origins, passages, access_alternatives into the new `ds_NNNN`
- [X] T047 [US1] Register US1 validation checks in src/copilot_ingest/stages/validate.py: every passage has at least one access alternative, anchor, fingerprint, extractor_version; alternatives are supersets of origin rules plus restricted groups; no quarantined path has rows; no child passage without parent; table passages contain headers
- [X] T048 [US1] Add US1 sections to the run report in src/copilot_ingest/stages/report.py: per-file outcome and reason, passage counts per document, quarantine list

**Checkpoint**: User Story 1 works on its own: T028-T032 pass; `copilot-ingest run` publishes a version with authorized passages from all text-based sources.

---

## Phase 4: User Story 2 - Unified asset and service history (Priority: P1)

**Goal**: One registry of machines and one chronological, deduplicated service history per machine
across MaintPro, Servio, and Salesforce, with legacy IDs and regional formats handled.

**Independent Test**: TAC-C-0142 E-14 history shows March 2026 and July 2026 once each, linked to
cases 00041207 and 00042388; `MFL-KM07` resolves to RTM-H-0007.

### Tests for User Story 2 ⚠️

- [X] T049 [P] [US2] Add US2 assertions to acceptance/ingestion_facts.yaml: Servio `02-12-2025` stored as 2025-12-02; Servio labour hours `2,5` stored as 2.5; `MFL-KM07` -> `RTM-H-0007`; Servio `Geannuleerd` -> `cancelled`; TAC-C-0142 E-14 events in 2026-03 and 2026-07, each once, linked to cases 00041207 and 00042388; every event has an access alternative equal to its export's rule
- [X] T050 [P] [US2] Write tests/unit/test_normalize_tabular.py: date parsing per source convention never inferred from value; decimal commas; status mapping; blank `object_oud` uses only the current ID; unknown asset creates an `unknown_asset` review item

### Implementation for User Story 2

- [X] T051 [US2] Implement src/copilot_ingest/stages/extract/tabular.py: read fleet_register.csv, maintpro_history_NA_2023-2026.csv, servio_export_EU_2023-2026.csv with pandas using config/sources.yaml (explicit delimiter, all columns read as strings), one record block per row with anchor `record_id` = WO_No or werkorder
- [X] T052 [US2] Implement source-convention normalization in src/copilot_ingest/stages/normalize.py: dates by declared format, decimal commas, status mapping to (`completed`, `open`, `cancelled`), event type mapping (MaintPro Inspection/PM/CM/Alarm/Firmware/Meter; Servio Inspectie/PO/Storing/Alarm/Software/Meterstand/F-gas controle) to (`inspection`, `preventive`, `corrective`, `alarm`, `firmware`, `meter`, `fgas_check`)
- [X] T053 [US2] Build assets, asset_aliases (from Servio `object_oud`), and site_aliases (asset ID prefix FRS/TAC/RTM/GDN; Servio `locatie` and fleet `site_name` variants) in src/copilot_ingest/stages/link.py
- [X] T054 [US2] Implement service event merge in src/copilot_ingest/stages/link.py: one event per maintenance row and per Salesforce case; link MaintPro rows citing `SF <case>` (and Servio rows citing case numbers) to the case as one event with both sources in `sources`; unresolved references -> `unresolved_link` review item
- [X] T055 [US2] Write assets, asset_aliases, site_aliases, service_events, and event access_alternatives (from each export's rule) into `ds_NNNN`, and create one search passage per event with `passage_id` linked, in src/copilot_ingest/stages/index.py
- [X] T056 [US2] Register US2 validation checks in src/copilot_ingest/stages/validate.py: every event has a non-null date and allowed status; every event asset exists in assets or has an open review item; no event counted twice across systems
- [X] T057 [US2] Add history counts per source, alias count, and unresolved links to the run report in src/copilot_ingest/stages/report.py

**Checkpoint**: User Stories 1 and 2 both work; `serving.events_for` returns the merged history for any visible machine.

---

## Phase 5: User Story 3 - Applicability, revision, and authority metadata (Priority: P2)

**Goal**: Documents and passages carry verified type, authority, models, revision, dates, and
applicability; bulletins are linked to affected machines; duplicates and revisions are related.

**Independent Test**: Inspect the dataset for the US3 facts without running the copilot.

### Tests for User Story 3 ⚠️

- [x] T058 [P] [US3] Add US3 assertions to acceptance/ingestion_facts.yaml: SB-2025-009 rule HCP-350 from HCP350-240001 at 38 N-m and FRS-P-0031 `affected`; HCP-350 units before HCP350-240001 `check_on_site` for SB-2025-009 (Version 2 cover condition); SB-2025-014 RTM-H-0007 `in_campaign` with code NK-C25-14; SB-2026-003 TAC-C-0142 (firmware 5.0) `affected`; VRS-75 Rev C supersedes Rev B; NK600_manual_final_v2.pdf is an origin of the Nordkyl NK-600 Rev C document; VRS Series Oil and Filter Quick Reference passages on VRS-75 intervals `possibly_stale`
- [x] T059 [P] [US3] Write tests/unit/test_quote_verification.py: value kept only when its quote is an exact normalized substring of the cited block and the value parses from the quote; otherwise field empty and `metadata_unverified` review item
- [x] T060 [P] [US3] Write tests/unit/test_bulletin_eval.py: serial range inclusive bounds, open-ended ranges, firmware comparison (`5.0` < `5.1.0`), market condition by region, variant condition -> `check_on_site`

### Implementation for User Story 3

- [x] T061 [US3] Implement document metadata extraction in src/copilot_ingest/stages/enrich.py: rules first (source system, title patterns from config/authority.yaml, model codes validated against fleet models), then `complete_json` with field-level `value`, `quote`, `block_id` for doc_type, revision, issue_date; enforce quote verification per research.md R7; derive authority_tier and controlled by rule only
- [x] T062 [US3] Implement bulletin rule extraction in src/copilot_ingest/stages/enrich.py: parse the bulletin applicability table rows (model, serial range, firmware, market, variant condition, outcome, campaign code, action) from structured table blocks; LLM fallback with quotes; each rule stored with quote and page
- [x] T063 [US3] Implement bulletin evaluation against the fleet register in src/copilot_ingest/stages/link.py producing bulletin_assets with status (`affected`, `in_campaign`, `not_affected`, `check_on_site`) and reason; declare dependency on fleet_register.csv so changes trigger recomputation
- [x] T064 [US3] Implement duplicate detection (identical normalized text -> one canonical document with multiple document_origins and one access alternative per origin) in src/copilot_ingest/stages/link.py
- [x] T065 [US3] Implement supersession (same model and doc_type, later revision or issue date) and `possibly_stale` marking for wiki or informal passages stating specs for a model with a newer controlled or manual source in src/copilot_ingest/stages/link.py
- [x] T066 [US3] Write documents metadata, document_relations, bulletin_rules, bulletin_assets into `ds_NNNN` and set passages.models and possibly_stale in src/copilot_ingest/stages/index.py
- [x] T067 [US3] Register US3 validation checks and report sections (metadata gaps by field, bulletins without verified applicability, duplicate and supersession counts) in src/copilot_ingest/stages/validate.py and src/copilot_ingest/stages/report.py

**Checkpoint**: US3 facts hold; applicability never defaults to "all units".

---

**US3 implementation notes**: All US3 logic lives in `stages/enrich.py` (metadata, bulletin rules,
evaluation, supersession, possibly_stale), not split across `link.py`; tests for T059/T060 are in
`tests/unit/test_enrich.py`. Rules found every revision and issue date in the corpus except the
HCP-200 scan (no text until US4 OCR), so the model fallback is not called. Bulletin rows come from
the applicability tables; one gpt-5.4-mini call per bulletin looks for conditions outside the table,
and a condition counts only if its quote is in the source and states its serial bound verbatim (the
bound is parsed from the quote, not taken from the model); it can only turn `not_affected` into
`check_on_site`. Units newer than every firmware a bulletin lists get `not_affected` with that
reason. Duplicates take their title from the highest-ranked source system
(`source_system_rank` in config/authority.yaml). possibly_stale requires a newer tier 1-3 document
for the same model and topic similarity >= 0.55 to one of its passages (embeddings already
computed). The 38 N-m torque in T058 is passage text, not a bulletin rule field, and is not
asserted. Fleet-register changes trigger recomputation because every stage after extraction reruns
on each build.


## Phase 6: User Story 4 - Difficult sources: scans, damaged files, other languages (Priority: P2)

**Goal**: Scans become text with cross-checked values and withheld disputed values; damaged files are
recovered and marked partial; non-English content is searchable with originals kept.

**Independent Test**: Ingest the HCP-200 scan and the damaged VRS-45 bulletin; inspect passages,
markers, flags, and translations.

### Tests for User Story 4 ⚠️

- [x] T068 [P] [US4] Add US4 assertions to acceptance/ingestion_facts.yaml: HCP-200 clearance passage contains either `0.38` and `0.50` with ocr `verified` or an `[[unverified:` marker, and never `2.10`; HCP-200 model recorded as HCP-200 (correction from HGP-200 logged); Vastra SB-2026-015 status `partial` with missing pages listed; Servio Dutch notes have text_en; bilingual Halden bulletin split into per-language blocks
- [x] T069 [P] [US4] Write tests/unit/test_ocr_crosscheck.py: aligned values that agree after normalization (decimal comma, unit spelling) -> verified; disagreeing or one-sided values -> replaced by `[[unverified:<item_id>|page=<n>]]` and `ocr_value_mismatch` review item; neither candidate appears in text; model code within edit distance 1 of a fleet model corrected and logged

### Implementation for User Story 4

- [x] T070 [P] [US4] Implement src/copilot_ingest/stages/extract/pdf_repair.py: on PyMuPDF errors or empty text pages, rewrite with pikepdf, re-extract, compare per-page yield, mark document `partial` with `missing_pages`
- [x] T071 [US4] Implement page rendering in src/copilot_ingest/stages/extract/pdf_scan.py: 300 dpi; TIFF for OCR input (Leptonica cannot read PNG on this machine) and PNG for viewing under `data/page_images/<fingerprint>/`
- [x] T072 [US4] Implement OCR pass A in src/copilot_ingest/stages/extract/pdf_scan.py: Tesseract CLI with `-l deu+eng` on the TIFF, word-level output with positions
- [x] T073 [US4] Implement OCR pass B in src/copilot_ingest/stages/extract/pdf_scan.py: `transcribe_image` with VISION_MODEL, prompt requiring verbatim transcription, tables as JSON rows, no inferred characters; structure taken from pass B
- [x] T074 [US4] Implement the value cross-check in src/copilot_ingest/stages/extract/pdf_scan.py per research.md R5: extract numbers with units, ranges, part numbers, model codes from both passes; align by table row label (rapidfuzz) or reading order; normalize; mark verified or withhold with marker and review item; correct model codes against fleet models; set passage `ocr` and `page_image`
- [x] T075 [P] [US4] Implement language detection per block with lingua and bilingual splitting (side-by-side EN/DE and SV/EN columns, interleaved NL/EN headings in KT-WI-14) in src/copilot_ingest/stages/normalize.py; link language pairs as `pairs_language_with` relations
- [x] T076 [US4] Implement src/copilot_ingest/stages/translate.py: translate non-English blocks without an English pair using LLM_MODEL_STRONG and config/glossary_nl_de_sv.yaml, cached by block hash; store text_en next to text_original; translate Servio and Dutch Salesforce notes into notes_en
- [x] T077 [US4] Register US4 validation checks and report sections (pages OCR'd, values verified, values withheld, partial documents with missing pages, translated block counts) in src/copilot_ingest/stages/validate.py and src/copilot_ingest/stages/report.py

**Checkpoint**: No unverified scanned value appears in retrievable text (SC-004); Dutch and German content is searchable in English.

---

**US4 implementation notes**: OCR lives in `stages/scan.py`, not in the extractor: the two reads
(Tesseract psm 4 and 6 via stdin, and VISION_MODEL at 200 dpi, the scan's native resolution) are
cached per file as a `scan` artifact; the value cross-check, withheld markers and model-code
correction rerun on every build against the current fleet models and reviewer decisions. Values are
compared by digits on the Tesseract line aligned with the row label (or the whole row when the label
is a position number), with running headers and footers removed. HCP-200 result: 72 critical
values, 62 verified, 10 withheld; HGP-200 and HCP-209 (Tesseract misreadings) corrected to HCP-200.
Revision A comes from the scan footer; the issue date (printed only as 03/1998) stays in review.
T070: on damage the extractor also tries a qpdf-repaired copy and keeps the one with more text
(for SB-2026-015 the original). T075: no document in the corpus exists as separate language files,
so there are no `pairs_language_with` relations; bilingual passages (English share >= 30%) are kept
whole and not translated. T076 deviates from the plan by approval: gpt-5.4-mini translates, and
each translation must have exactly the original's numbers, codes and withheld markers (nothing
dropped or added); failures are retried once with LLM_MODEL_STRONG. Translations are cached per
text in `data/artifacts/_translations/`. Every paid call is logged to `data/usage.jsonl`.
US4 spend: OCR $0.35 (8 gpt-5.5 calls), translation $0.05 (6 gpt-5.4-mini calls, no retries).

## Phase 7: User Story 5 - Running corpus: incremental updates and safe publishing (Priority: P2)

**Goal**: Changes reprocess only affected documents; deletions and access changes propagate; failed
runs never replace the published version.

**Independent Test**: Modify, delete, and re-permission one document each; confirm only they change;
force a validation failure and confirm the previous version remains published.

### Tests for User Story 5 ⚠️

- [X] T078 [P] [US5] Write tests/integration/test_incremental.py: two runs on an unchanged corpus produce identical passage IDs and texts (SC-005); changing one wiki file changes only its passages and dependent relations; deleting a file removes its passages and events from the next version; tightening a rule in a temporary permissions.json copy removes visibility for affected users (SC-007)
- [X] T079 [P] [US5] Write tests/integration/test_publish_gate.py: a run with a failing acceptance fact exits 2 and `control.published` still points to the previous version; `rollback` restores a retained version

### Implementation for User Story 5

- [X] T080 [US5] Implement dependency hashing in src/copilot_ingest/pipeline.py: each stage declares dependencies (fleet_register.csv for bulletin evaluation and aliases; approved markers for restricted tagging; resolutions for affected items); a dependency change invalidates dependent artifacts only
- [X] T081 [US5] Implement removal handling in src/copilot_ingest/stages/register.py: files absent from the corpus become `removed` in control.source_files and contribute no rows to the new version
- [X] T082 [US5] Implement version retention (keep last 3 published versions, drop older `ds_NNNN` schemas) and the `rollback VERSION` command in src/copilot_ingest/stages/publish.py and src/copilot_ingest/cli.py
- [X] T083 [US5] Implement `--only`, `--from-stage`, `--no-publish`, and `--offline` options in src/copilot_ingest/cli.py and src/copilot_ingest/pipeline.py per contracts/cli.md
- [X] T084 [US5] Add changed, unchanged, removed file counts and changed passage counts to the run report in src/copilot_ingest/stages/report.py

**Checkpoint**: Re-running is idempotent; single-document updates publish quickly; failures are contained.

---

## Phase 8: User Story 6 - Ingestion report and review queue (Priority: P3)

**Goal**: The operator sees every file's outcome and can resolve flagged items, with resolutions
applied on the next run.

**Independent Test**: Every source file appears in the report with one outcome; a resolved OCR item
replaces its marker with the confirmed value on the next run.

### Tests for User Story 6 ⚠️

- [X] T085 [P] [US6] Write tests/integration/test_review_flow.py: resolving the HCP-200 clearance item with `"0,38 - 0,50 mm"` replaces the marker on the next run and marks the value `reviewer_verified`; the item no longer appears as open; every file in the corpus appears exactly once in report.json (SC-002)

### Implementation for User Story 6

- [X] T086 [US6] Implement `review list`, `review show` (source location, candidates, reason, page image path), and `review resolve ITEM_ID --value VALUE --note TEXT` in src/copilot_ingest/cli.py backed by src/copilot_ingest/review.py
- [X] T087 [US6] Apply resolutions in the stages that raised them: OCR values in src/copilot_ingest/stages/extract/pdf_scan.py, metadata in src/copilot_ingest/stages/enrich.py, restricted borderline and marker approval in src/copilot_ingest/stages/restricted.py, unresolved links in src/copilot_ingest/stages/link.py
- [X] T088 [US6] Complete the run report in src/copilot_ingest/stages/report.py: all sections in contracts/cli.md (`report`), review items grouped by kind with source locations, access-rule coverage percentage, validation results; implement `report [--run] [--json]` in src/copilot_ingest/cli.py
- [X] T089 [P] [US6] Implement `visible --user USER_ID [--doc PATH] [--search TEXT]` in src/copilot_ingest/cli.py using only the serving functions

**Checkpoint**: All user stories are independently functional.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: End-to-end validation and hardening across stories

- [ ] T090 Run every step in specs/001-corpus-ingestion-pipeline/quickstart.md on the real corpus and record results in data/reports/quickstart-validation.md
- [ ] T091 Measure a full run and a single-document `--only` run against SC-006 (30 minutes, 5 minutes) and record timings in the run report
- [ ] T092 [P] Add an access-rule file guard in src/copilot_ingest/acl.py: refuse to run if permissions.json references groups not defined in users.json, or if any user belongs to an undefined group
- [ ] T093 [P] Add a README section "Ingestion" (setup, run, review, rollback) linking to quickstart.md in README.md
- [ ] T094 Run ruff and the full test suite (`pytest -m "not hosted"` offline from cache, then `pytest`) and fix failures

### Serving additions for the answer side (specs/contracts/serving-additions.md)

- [x] T095 Add view `serving.restricted_procedures` (name, title, doc_id, required_groups alternatives) in src/copilot_ingest/db/serving.sql, populated from controlled documents whose groups include a cert-* group; no content columns
- [x] T096 Add `serving.page_fully_visible(groups, doc_id, page)` in src/copilot_ingest/db/serving.sql covering page ranges (`page` to `page_end`), with an ACL grid test in tests/integration/ that NK600 8.3 and 8.4 pages are not fully visible to u06 (chiller technician without refrigerant certification)
- [x] T097 Add `serving.dataset_info()` (dataset version, published time, embedding model and dimensions) in src/copilot_ingest/db/serving.sql, written at publish
- [x] T098 Publish `serving.restricted_markers` (procedure, marker, approved or proposed) for server-side leak guards, written per dataset from the restricted stage
- [x] T099 Add `serving.hidden_exists(groups, ids, embedding, max_distance)`, with a test that identifiers alone are too coarse (u12 (NA conveyor technician) and BX-20 (Belton conveyor model))
- [ ] T100 Publish a dataset with `serving.identifier_search` ordered by `matches DESC, passage_id` (source changed 2026-10-13; ds_0028 still has the plan-dependent order, which the engine works around)
- [ ] T101 Separate the subject asset of a case or record from assets it only mentions (case 00041988 (Salesforce case about FRS-P-0031) lists FRS-P-0012 because "duty switched to FRS-P-0012"), so `asset_ids` tags only the subject

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none
- **Foundational (Phase 2)**: depends on Setup; blocks all stories
- **US1 (Phase 3)** and **US2 (Phase 4)**: depend on Foundational; independent of each other
- **US3 (Phase 5)**: depends on US1 (passages and documents) and US2 (fleet register for bulletin evaluation)
- **US4 (Phase 6)**: depends on US1 (extraction framework, chunking, indexing); translation of history notes also uses US2 outputs
- **US5 (Phase 7)**: depends on Foundational; most valuable after US1-US2
- **US6 (Phase 8)**: depends on stages that raise review items (US1, US3, US4)
- **Polish (Phase 9)**: depends on all stories

### Within Each User Story

- Assertions and tests first, confirmed failing
- Extractors before normalization, normalization before linking, linking before indexing
- Validation checks and report sections last

### Parallel Opportunities

- Setup: T003-T008
- Foundational: T015, T016, T017, T019, T022, T023, T027 alongside the migration chain T009-T014
- US1: tests T028-T032; extractors T034-T040 (different files)
- US2 can proceed alongside US1 after Foundational
- US4: T070 and T075 alongside the scan chain T071-T074

---

## Parallel Example: User Story 1

```bash
Task: "Add US1 assertions to acceptance/ingestion_facts.yaml"
Task: "Write tests/acl/test_visibility_grid.py"
Task: "Write tests/unit/test_chunk.py"

Task: "Implement src/copilot_ingest/stages/extract/docx.py"
Task: "Implement src/copilot_ingest/stages/extract/html.py"
Task: "Implement src/copilot_ingest/stages/extract/messages.py (Teams)"
Task: "Implement src/copilot_ingest/stages/extract/messages.py (Salesforce)"
```

---

## Implementation Strategy

### MVP First (User Stories 1 and 2)

1. Phase 1 Setup, Phase 2 Foundational
2. Phase 3 (US1): authorized passages; validate with the ACL grid
3. Phase 4 (US2): asset registry and merged history
4. **Stop and validate**: the query feature can start against the serving contract here

US1 alone is a usable MVP for lookups; US1 plus US2 covers the history and asset questions that
roughly half the evaluation depends on.

### Incremental Delivery

1. US3 next: applicability and revisions fix the most dangerous wrong answers (torque, oil interval)
2. US4: scans, damaged files, languages
3. US5: incremental and safe publishing for the running corpus
4. US6: operator report and review queue

### Solo Build Order (one developer)

Follow phases in order. Within US1, build extractors in order of evaluation value: DOCX, HTML,
Salesforce and Teams JSON, email, native PDF. Start the OCR spike (T071-T074) early as a
throwaway check if the clearance cross-check looks at risk, since the scan is the biggest
schedule risk.

---

## Notes

- [P] tasks touch different files and have no dependencies on incomplete tasks
- Hosted-model tests are marked `hosted`; all other tests run offline from the cache
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently

## Implementation notes (Phases 1-4)

- T018: only extraction is cached per fingerprint and extractor version
  (`data/artifacts/<fp>/extract-<name>@<version>.json`); chunking, linking, tagging and access are
  cheap and recomputed every run, so access-rule changes always take effect.
- T019-T021: chat and vision calls are not exercised yet (no stage uses them before US3/US4).
- T045, T046: embeddings run (text-embedding-3-large, 1024 dims, cached in `cache.embeddings`,
  committed per batch). Whole-passage similarity was replaced by step-against-step matching after
  calibration on ds_0008: whole passages scored 0.70-0.78 on topic alone (warnings, contents pages,
  reference lists). See `config/restricted_markers.yaml` for the rule and thresholds.
- Restriction spreads within a parent/child pair: a tagged child tags its parent; a tagged parent
  tags every child holding a matched step or marker.
- Restricted markers: HV-PROC-07 markers are applied and await approval (`marker_approval`).
  HV-PROC-02, CS-PROC-03 and SOP-020 have no distinctive markers; their protection relies on the
  similarity check.

## Implementation notes (Phases 7-8)

- T080: per-stage dependency hashing was not built. Only extraction is cached (by fingerprint and
  extractor version); every later stage reruns on each build (about 18 s for the corpus), so changes
  to fleet_register.csv, approved markers, access rules and resolutions always take effect.
- T083: `--only` re-extracts the listed files and builds a complete dataset that publishes normally
  (it previously built a dataset with only those files). `--from-stage` accepts `extract` only.
- T085: the HCP-200 OCR resolution flow moves to US4; review decisions are tested per stage in
  tests/unit/test_review.py and the resolve path in tests/integration/test_review_flow.py.
- T087: decisions are looked up by the item ID a stage would raise, so a changed source needs a fresh
  decision. OCR and metadata decisions get applied when US4 and US3 build those stages.
- Added: `obsolete` review status (migration 003) for items the latest run no longer raises.
- Fixed: `prune` kept the newest 3 versions even when they failed validation; it now keeps the last 3
  published versions, the serving version, and the newest build.
- T078/T079 run against a scratch database `copilot_ingest_test` with a copy of the corpus; caches
  are copied in and back so they cost only the embeddings of edited text.
- Added beyond the tasks: `config/restricted_markers.yaml`, `stages/classify.py`,
  `serving.document_origins`, validation check `page_coverage`, fact types for US2.
- Known extraction gap: the borderless fault-code table in VRS-110 section 7.4 is extracted as lines,
  not a table.
