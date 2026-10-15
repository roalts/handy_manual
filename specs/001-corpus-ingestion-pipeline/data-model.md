# Data Model: Corpus Ingestion Pipeline

Schemas: `control` (persistent), `cache` (persistent), `ds_NNNN` (one per dataset version),
`serving` (views over the published version). Types are Postgres types.

## control schema

### control.runs
| Column | Type | Notes |
|---|---|---|
| run_id | text PK | `YYYYMMDD-HHMMSS` |
| started_at, finished_at | timestamptz | |
| dataset_version | text | `ds_NNNN` built by this run |
| outcome | text | `published`, `built` (not published: `--no-publish` or `--only`), `validation_failed`, `error` |
| report_path | text | `data/reports/<run_id>/report.md` |

### control.source_files
| Column | Type | Notes |
|---|---|---|
| path | text PK | corpus-relative path |
| fingerprint | text | SHA-256 of file bytes |
| size_bytes | bigint | |
| source_system | text | from access rules file |
| required_groups | text[] | null if no rule |
| status | text | `active`, `quarantined`, `partial`, `removed` |
| first_seen_run, last_seen_run | text | |

### control.quarantine
| Column | Type | Notes |
|---|---|---|
| path | text | |
| run_id | text | |
| stage | text | `register`, `extract`, ... |
| reason | text | `no_access_rule`, `unknown_group`, `empty_file`, `unreadable`, `unsupported_format` |
| detail | text | |

### control.review_items
| Column | Type | Notes |
|---|---|---|
| item_id | text PK | hash of (fingerprint, stage, anchor, field) |
| kind | text | `ocr_value_mismatch`, `metadata_unverified`, `restricted_borderline`, `marker_approval`, `unresolved_link`, `unknown_asset` |
| path, anchor | text | source location |
| field | text | |
| candidates | jsonb | e.g. `{"tesseract":"2.10","vision":"0,38"}` |
| reason | text | |
| status | text | `open`, `resolved`, `obsolete` (no longer raised by the latest run; reopens if raised again) |
| first_run, last_run | text | |

### control.resolutions
| Column | Type | Notes |
|---|---|---|
| item_id | text PK FK | |
| value | jsonb | confirmed value or decision |
| resolved_by, resolved_at, note | text, timestamptz, text | |

### control.published
Single row: `dataset_version`, `published_at`, `run_id`.

## cache schema

- `cache.model_calls(key text PK, provider, model, prompt_version, input_hash, output jsonb,
  created_at)`: key = hash(provider, model, prompt_version, input_hash).
- `cache.embeddings(text_hash text, model text, dims int, embedding vector(1024), PK(text_hash, model))`.

## ds_NNNN schema (one dataset version)

### documents
| Column | Type | Notes |
|---|---|---|
| doc_id | text PK | canonical ID: hash of normalized full text |
| title | text | content-derived, not embedded metadata |
| doc_type | text | `controlled_procedure`, `work_instruction`, `bulletin`, `service_manual`, `wiki`, `email`, `chat`, `case_export`, `maintenance_export`, `fleet_register`, `report` |
| authority_tier | int | 1 controlled procedure or work instruction, 2 bulletin, 3 manual, 4 wiki, 5 email or chat; records and exports are tier 0 (factual records) |
| controlled | bool | |
| models | text[] | validated against fleet models |
| revision | text | e.g. `Rev C` |
| issue_date | date | |
| languages | text[] | |
| status | text | `active`, `superseded`, `partial` |
| missing_pages | int[] | for partial documents |
| extractor_version | text | |

### document_origins
`(doc_id, path, fingerprint, source_system, required_groups text[])`. More than one row means
duplicates collapsed into one canonical document (FR-021).

### document_relations
`(from_doc, to_doc, relation, quote, page)`; relation in `supersedes`, `possibly_stale_vs`,
`duplicate_of`, `pairs_language_with`.

### bulletin_rules
| Column | Type | Notes |
|---|---|---|
| rule_id | text PK | |
| doc_id | text FK | bulletin |
| model | text | |
| serial_from, serial_to | text | inclusive; null means open-ended |
| firmware_condition | text | e.g. `< 5.1.0`; parsed into `firmware_lt`, `firmware_gte` |
| market_condition | text | e.g. `EU deliveries` mapped to region `EU` |
| variant_condition | text | verbatim, e.g. `earlier pumps fitted with a Version 2 cover` |
| outcome | text | `affected`, `in_campaign`, `not_affected` |
| campaign_code | text | |
| action_summary | text | |
| quote, page | text, int | verified quotation |

### bulletin_assets
`(doc_id, asset_id, status, rule_id, reason)`; status in `affected`, `in_campaign`,
`not_affected`, `check_on_site`. Recomputed when a bulletin or the fleet register changes.

### passages
| Column | Type | Notes |
|---|---|---|
| passage_id | text PK | hash(doc_id, anchor, normalized text) |
| doc_id | text FK | |
| role | text | `standard`, `parent`, `child` |
| parent_passage_id | text | for child passages |
| anchor | jsonb | `{page, page_end, section_path, table, record_id, message_id}` |
| heading_path | text[] | |
| block_types | text[] | e.g. `procedure_step`, `table`, `warning` |
| lang | text | |
| text_original | text | may contain withheld-value markers |
| text_en | text | |
| fault_codes, part_numbers, asset_ids, serials, case_numbers | text[] | canonical forms, GIN indexed |
| models | text[] | |
| restricted_tags | text[] | procedure IDs whose content this passage reproduces |
| ocr | text | `none`, `verified`, `has_withheld_values` |
| page_image | text | path for scanned pages |
| possibly_stale | bool | |
| tsv | tsvector | `simple` config over text_en and text_original |
| embedding | vector(1024) | |
| fingerprint, extractor_version, ingested_at | text, text, timestamptz | provenance |

### access_alternatives
`(object_type, object_id, alt_no, required_groups text[])` where object_type in `document`,
`passage`, `event`. Visibility rule: some alternative has every required group in the user's
groups. No rows means invisible.

### assets
`(asset_id PK, model, serial, site, site_name, customer, region, install_date, firmware,
oil_type, contract_end)`.

### asset_aliases
`(alias PK, asset_id, source)`, e.g. `MFL-KM07 -> RTM-H-0007 (servio.object_oud)`.

### site_aliases
`(alias PK, site)`, e.g. `Rotterdam DC Maasvlakte -> RTM`.

### service_events
| Column | Type | Notes |
|---|---|---|
| event_id | text PK | |
| asset_id | text FK | resolved through aliases |
| event_date | date | parsed per source convention |
| event_type | text | normalized: `inspection`, `preventive`, `corrective`, `alarm`, `firmware`, `meter`, `fgas_check`, `case` |
| fault_code | text | canonical |
| status | text | `completed`, `open`, `cancelled` |
| notes_original, notes_en | text | |
| parts | text[] | |
| labor_hours, run_hours | numeric | decimal commas converted |
| technician | text | |
| sources | jsonb | `[{system:"maintpro", record_id:"231262"}, {system:"salesforce", case:"00042851"}]` |
| passage_id | text | the passage representing this event for search |

## Relationships

- `documents 1-* passages`; `documents 1-* document_origins`; `documents *-* documents` via
  `document_relations`.
- `bulletin_rules *-1 documents`; `bulletin_assets` links bulletins to `assets`.
- `assets 1-* asset_aliases`; `assets 1-* service_events`.
- `passages`, `documents`, `service_events` each have `access_alternatives`.

## Validation rules (enforced at build or validate stage)

- Every passage, document, and event has at least one access alternative (fail closed otherwise:
  invisible, and the run fails validation).
- Each passage's alternatives are supersets of every origin alternative of its document, plus the
  groups from `restricted_tags`.
- Every passage has a non-null anchor, fingerprint, extractor_version.
- No passage text contains an OCR value with status other than `verified` or `reviewer_verified`;
  withheld values appear only as markers.
- Table passages contain their header; no child passage lacks its parent.
- `service_events.event_date` is not null; `status` in the allowed set; every event's `asset_id`
  exists in `assets` or a review item exists.

## State transitions

- **Source file**: `new -> active | quarantined`; `active -> partial` (recoverable damage);
  `active | partial -> removed` (file deleted); `quarantined -> active` (cause fixed).
- **Review item**: `open -> resolved` (resolution applied next run); reopened if the source changes.
- **Withheld OCR value**: `withheld -> reviewer_verified` (resolution) or `-> verified` (both passes
  agree after re-run).
- **Document**: `active -> superseded` when a newer revision for the same model and type arrives.
- **Dataset version**: `building -> validated -> published -> retired`, or
  `building -> validation_failed`.
