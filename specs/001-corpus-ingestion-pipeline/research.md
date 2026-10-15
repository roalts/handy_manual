# Research: Corpus Ingestion Pipeline

Decisions for every open technical question in the plan. Evidence comes from probing the actual
corpus on 2026-10-11 unless noted.

## R1. Storage layout

- **Decision**: Postgres 17 + pgvector in one database with four schemas: `control` (runs, source
  files, quarantine, review queue, resolutions, published pointer; survives rebuilds), `cache`
  (hosted-model call results and embeddings keyed by content hash), `ds_NNNN` (one schema per
  dataset version), and `serving` (views the query feature reads). Raw copies, stage artifacts,
  page images, and reports live on disk under `data/`.
- **Rationale**: one store means access filtering and search happen in one query; per-version
  schemas make atomic publishing trivial; on-disk artifacts make each stage inspectable.
- **Alternatives**: SQLite (no production path, weaker concurrency); Qdrant plus a relational
  store (access rules duplicated across two systems).

## R2. Dataset versioning and atomic publish

- **Decision**: each run builds a fresh `ds_NNNN` schema from stage artifacts (expensive stages are
  cached, so a rebuild is seconds of database writes at this scale). Validation runs against the
  new schema. Publish is one transaction that recreates the `serving` views to point at the new
  schema and updates `control.published_version`. Keep the last 3 versions for rollback.
- **Rationale**: a failed or partial run can never affect what the query feature sees (FR-034).
  Rebuilding the tables instead of patching them guarantees deletions propagate (FR-033).
- **Alternatives**: in-place upserts (deletion and partial-failure bugs); copy-on-write per row
  (complex, no benefit at this scale).

## R3. Incremental processing and determinism

- **Decision**: a document is reprocessed in a stage when its fingerprint, its access rule, the
  stage's version string, or a declared dependency changed (for example the fleet register for
  bulletin-to-asset links). Stage artifacts are stored at
  `data/artifacts/<fingerprint>/<stage>@<stage_version>.json`. Hosted-model calls are cached by
  (input hash, prompt version, model id) and pinned to dated model snapshots; the cache, not
  sampling settings, is what makes reruns identical (the GPT-5.x models reject a `temperature`
  parameter, verified 2026-10-11). Passage IDs are hashes of
  (canonical document ID, anchor, normalized text), so unchanged passages keep their IDs.
- **Rationale**: satisfies FR-032 and SC-005; caching makes reruns free and repeatable even if a
  hosted model is not perfectly deterministic.
- **Alternatives**: timestamps for change detection (unreliable across exports).

## R4. Access representation

- **Decision**: each passage, service event, and document has one or more *access alternatives*;
  each alternative is a set of required groups (possibly empty). A user can see a row if at least
  one alternative's groups are all in the user's groups. Restricted-content tags add their groups to
  every alternative. A row with no alternatives is invisible. Visibility is implemented once, as a
  SQL function in `serving`, and every serving view is defined through it.
- **Rationale**: handles duplicates correctly ("either copy") without loosening any rule; fail
  closed by construction, because a missing alternative means `EXISTS` finds nothing.
- **Alternatives**: one group array per row (cannot express duplicates); post-filtering in
  application code (easy to bypass).

## R5. Scanned documents: two-pass OCR and cross-check

- **Decision**: render each page at 300 dpi; OCR pass A with the Tesseract CLI (`deu+eng`, TIFF
  input); pass B with a hosted vision model instructed to transcribe verbatim, including tables
  row by row as JSON, and never to infer missing characters. Extract critical values (numbers with
  units, ranges, part numbers, model codes) from both passes with the same patterns; align them by
  table row label (fuzzy match on the label text) or by reading order within a block; normalize
  (decimal comma, unit spelling); compare. Agreeing values are verified. Disagreeing or one-sided
  values are withheld and a review item is created. Model codes are corrected against the fleet
  model list (edit distance 1, logged). The vision transcription supplies the text structure; pass A
  is used only for verification.
- **Evidence**: on HCP-200 page 3, Tesseract produced "Spaltmaß Laufrad - Gehäuse (diametral) 2.10
  050 mm" (expected 0,38-0,50 mm) and "HGP-200" for "HCP-200"; table layout was lost. Tesseract
  cannot read PNG on this machine (Leptonica error); TIFF works.
- **Withheld value marker** (consumed by the query feature): `[[unverified:<review_item_id>|page=<n>]]`
  in passage text, with the page image referenced from the passage record.
- **Alternatives**: Tesseract only (shown wrong); vision only (no independent check against
  plausible-but-invented values).

## R6. Damaged PDFs

- **Decision**: open with PyMuPDF; if errors occur or any page yields no text and no images,
  rewrite the file with pikepdf (qpdf repair) and extract again; compare per-page yield; mark the
  document `partial` and list pages still empty. Pages with images but no text go to the scan path.
- **Evidence**: `Vastra_SB-2026-015_VRS-45_Coupling.pdf` raises zlib and page-tree errors; page 2
  yields 0 characters.

## R7. Quote verification for automated extraction

- **Decision**: extraction prompts return JSON with, for each field, `value`, `quote`, and the
  block ID. Code normalizes both quote and block text (Unicode NFKC, casefold, collapse whitespace,
  join hyphenated line breaks) and requires the quote to be an exact substring of that block. The
  value must also be derivable from the quote by a field-specific parser (dates, revisions, serial
  ranges, firmware conditions). Failing fields are left empty and a review item is created.
- **Rationale**: FR-020; prevents plausible invented metadata.
- **Alternatives**: fuzzy quote matching (lets paraphrased or invented quotes pass).

## R8. Bulletin applicability

- **Decision**: model applicability as rule rows: model, serial from and to (inclusive), firmware
  condition, market or region condition, hardware-variant condition (free text), outcome
  (`affected`, `in_campaign`, `not_affected`), action summary, quote, page. Extract rows from the
  bulletin's applicability table (structured table extraction first, LLM with quotes as fallback).
  Evaluate each fleet machine against the rules in code, producing `affected`, `not_affected`, or
  `check_on_site` (when a rule depends on a condition the fleet register does not hold, such as a
  replacement casing cover).
- **Evidence**: SB-2025-009 has two serial bands with different torques plus a "Version 2 cover on
  earlier pumps" condition; SB-2025-014 splits the same serial range by market (EU in campaign,
  outside EU not affected) and names a campaign code; SB-2026-003 combines a serial range with
  installed firmware; SB-2025-018 is a part supersession across a serial range.
- **Expected results**: FRS-P-0031 (HCP350-241187) affected by SB-2025-009; RTM-H-0007
  (NK600-230415, EU) in campaign NK-C25-14; TAC-C-0142 (VRS-110, firmware 5.0) affected by
  SB-2026-003; pre-240001 HCP-350 units `check_on_site` for SB-2025-009 (cover version unknown).

## R9. Restricted-content tagging

- **Decision**: (1) Identify restricted procedures as controlled documents whose access rule
  includes a certification group (HV-PROC-02, HV-PROC-07, SOP-020, CS-PROC-03). (2) Generate
  candidate markers from their step passages: identifiers and phrases that are rare elsewhere in the
  corpus (parameters like `P9.01`, test points `TP1`/`TP2`, specific thresholds such as `50 V DC`
  together with the action). (3) The operator approves the list into
  `config/restricted_markers.yaml` (review item on first run). (4) Tag any passage outside the
  procedure that contains two or more approved markers of one procedure, or whose embedding
  similarity to one of its step passages exceeds a threshold calibrated on the corpus; tagging adds
  that procedure's certification groups. Borderline scores create a review item and are restricted
  until resolved. Document names alone (for example "per HV-PROC-07") are never markers.
- **Rationale**: FR-005; references that say "HV work, use HV-PROC-07" must stay visible because
  they ground the "you need certification" response.
- **Acceptance**: the Compressor Troubleshooting Playbook E-31 section and the Work Order Writing
  Guide remain visible to u03; any passage reproducing the reset steps is not.

## R10. Normalization conventions per source

- **Decision**: per-source conventions in `config/sources.yaml`: MaintPro (comma, `MM/DD/YYYY`,
  English), Servio (semicolon, `DD-MM-YYYY`, decimal comma, Dutch headers and notes, status values
  Gereed/Open/Geannuleerd), Salesforce (ISO timestamps, nested comments and emails), Teams (ISO,
  HTML bodies, `replyToId`, `deletedDateTime`, `lastEditedDateTime`), fleet register (`M/D/YYYY`).
  Never infer a date format from a value. Asset aliases from Servio `object_oud` (63 of 447 blank).
  Site resolved by asset ID prefix (FRS, TAC, RTM, GDN) with a site alias table.
- **Evidence**: Servio row `02-12-2025;GDN-C-0131;...;E-31` must be 2 December 2025; labour hours
  `2,5`; MaintPro notes reference `SF 000xxxxx` in 35 rows.

## R11. Language and translation

- **Decision**: detect language per block with lingua; split bilingual documents into
  per-language blocks (bulletins print EN/DE or SV/EN side by side; KT-WI-14 interleaves NL/EN
  headings). Translate non-English blocks with the hosted LLM using the domain glossary, cache by
  block hash, store `text_en` next to `text_original`. Where a bilingual document already contains
  the English version, link the pair instead of translating.
- **Rationale**: FR-017 and FR-031 (searchable from English, original kept for citation).

## R12. Chunking

- **Decision**: group blocks by heading path; one passage per section up to 500 tokens; numbered
  procedures never split, procedures over 800 tokens become a parent passage (delivered whole) with
  child passages of about three steps (used for search only); tables keep their header row, large
  tables split into row groups with the header repeated; one passage per case (with comments and
  emails), maintenance record, chat thread, and email message; unstructured prose falls back to
  sentence windows of 300-500 tokens with about 50 tokens overlap. Embedded text is
  `heading_path + text_en` (plus original text for non-English passages).
- **Validation**: checks that no procedure was split without a parent and that every table passage
  contains its header.

## R13. Embeddings and keyword search

- **Decision**: OpenAI `text-embedding-3-large` with `dimensions=1024`, stored in a pgvector column;
  exact cosine search (no ANN index needed below about 100k passages). Keyword search uses Postgres
  full-text search over `text_en` and `text_original` with the `simple` configuration, plus exact
  identifier arrays (`fault_codes`, `part_numbers`, `asset_ids`, `serials`, `case_numbers`) with GIN
  indexes.
- **Evidence**: Postgres tokenizes `E-31` into `e` and `-31`, and `SB-2026-003` into fragments, so
  identifiers need their own exact-match columns.
- **Alternatives**: ParadeDB BM25 (Docker image only; not worth the setup for a solo build);
  Cohere multilingual embeddings (equally suitable; provider adapter allows a switch).

## R14. Hosted provider

- **Decision**: OpenAI as the default provider for vision transcription, translation, metadata
  extraction, and embeddings, behind `providers/base.py`. Model IDs are configuration, recorded with
  every cached call. Requires `OPENAI_API_KEY` in `.env`. Pinned snapshots: fast
  `gpt-5.4-mini-2026-03-17`, strong and vision `gpt-5.5-2026-04-23`, embeddings
  `text-embedding-3-large` at 1024 dimensions. Calls use the Responses API with strict JSON-schema
  output and no `temperature` parameter.
- **Rationale**: one key covers all four uses; the adapter keeps a switch to another provider to a
  single module.
- **Open item for the operator**: confirm the provider and key before implementation starts.

## R15. Email and chat specifics

- **Decision**: `.eml` via the standard library (plain-text part preferred, HTML as fallback);
  email printed to PDF (the HCP-350 Halden thread) is parsed from PDF text by splitting on
  `From:`/`Sent:` header blocks. Quoted history is removed when the quoted message also exists as
  its own message in the thread; otherwise kept. Teams: rebuild threads from `replyToId`, drop
  messages with `deletedDateTime`, keep latest edit, strip HTML, record attachments by name.

## R16. Review queue and reviewer resolutions

- **Decision**: review items live in `control.review_items` with a stable key (fingerprint, stage,
  anchor, field) so the same issue maps to the same item across runs. Resolutions are stored in
  `control.resolutions` and applied in the stage that raised the item on the next run (for
  example, a confirmed OCR value replaces its marker and is marked `reviewer_verified`).
