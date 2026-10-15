# Contract: Serving additions for the answer side

Owner: 001 ingestion. Consumers: 002 answer engine, 003 answer API. These extend
[serving.md](../001-corpus-ingestion-pipeline/contracts/serving.md) and follow its guarantees.
Status: built (T095–T097 in 001 tasks.md), live from ds_0027 (dataset version 27).

## Restricted procedure names

```sql
serving.restricted_procedures  -- view, one row per access alternative
  name text              -- "HV-PROC-07"
  title text             -- "HV-PROC-07 VRS-110 VFD Fault Reset"
  doc_id text
  alt_no int
  required_groups text[] -- the user can satisfy the procedure if any row's groups <@ theirs
```

Names and titles only, never content. Visible passages already mention these names ("follow
HV-PROC-07"), so the names are not secret. The engine uses this to tell "certification required"
apart from "no source": when visible passages name a procedure the user can't satisfy, the answer
is `restricted` with `missing_groups` computed from these alternatives.

## Page visibility

```sql
serving.page_fully_visible(p_groups text[], p_doc_id text, p_page int) RETURNS boolean
-- true iff every passage of the document anchored on that page (including page ranges) is
-- visible to p_groups
```

Used by the API before returning a page image (see http-api.md, Sources).

## Dataset and embedding settings

```sql
serving.dataset_info() RETURNS TABLE (dataset_version text, published_at timestamptz,
                                       embedding_model text, embedding_dims int)
```

The engine must embed questions with exactly this model and dimension
(`text-embedding-3-large`, 1024 in ds_0026) and must refuse to start if they differ from its own
settings.

## Hidden content exists

```sql
serving.hidden_exists(p_groups text[], p_ids text[],
                      p_embedding vector(1024) DEFAULT NULL,
                      p_max_distance double precision DEFAULT NULL) RETURNS boolean
-- true iff some passage not visible to p_groups has identifiers (fault codes, part numbers, asset
-- IDs, serials, case numbers, models) overlapping p_ids and, when p_embedding is given, a cosine
-- distance to it of at most p_max_distance
```

Lets the engine say "not visible to you" (`abstain_reason: not_visible`) only when relevant hidden
content exists. It reveals existence, never content, which the constitution requires anyway.

**Identifiers alone are too coarse.** In ds_0028 (dataset version 28), `hidden_exists` for u12
(NA conveyor technician) and `{BX-20}` is true because EU (Europe) belt-change records mention the
BX-20, although nothing hidden is about its warranty. Called that way, q07 (BX-20 warranty) would
wrongly say "not visible to you" instead of "no permitted source". Always pass the question's
embedding and a calibrated distance; calibration must keep q07 false.

## Restricted markers (leak guards only)

```sql
serving.restricted_markers  -- view
  procedure text  -- "HV-PROC-07"
  marker text     -- canonical form, e.g. "TP1", "100 MOHM" (upper case, single spaces)
  status text     -- 'approved' (reviewed) or 'proposed' (applied until reviewed: fail closed)
```

For server-side guards only: an answer to a user who can't satisfy the procedure must contain none
of its markers. Compare case-insensitively after collapsing whitespace. Never send these to a
model or a client. This replaces any marker list kept in engine code; the list changes when a
reviewer approves or rejects markers.
