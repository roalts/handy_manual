# Contract: Serving Dataset (read by the query feature)

The query feature reads only the `serving` schema. It never reads `ds_NNNN`, `control`, or `cache`
directly. Every object below already applies the visibility rule; callers pass the user's groups,
which they obtain from the trusted identity source, never from conversation content.

## Visibility function

```sql
serving.can_see(object_type text, object_id text, user_groups text[]) RETURNS boolean
-- true iff some access alternative of the object has required_groups <@ user_groups
-- false if the object has no access alternatives (fail closed)
```

## Set-returning functions (preferred entry points)

| Function | Returns |
|---|---|
| `serving.passages_for(user_groups text[])` | passages visible to the user (all columns in data-model `passages`, except `embedding` exposed separately) |
| `serving.events_for(user_groups text[])` | service events visible to the user |
| `serving.documents_for(user_groups text[])` | documents visible to the user, with relations |
| `serving.keyword_search(user_groups text[], query text, k int)` | visible passages ranked by full-text match |
| `serving.vector_search(user_groups text[], query_embedding vector(1024), k int)` | visible passages ranked by cosine similarity (exact) |
| `serving.identifier_search(user_groups text[], ids text[], k int)` | visible passages whose identifier arrays overlap `ids` |

Filtering happens inside each function before ranking, so a user's results are never reduced by
restricted rows.

## Unrestricted reference data

`serving.assets`, `serving.asset_aliases`, `serving.site_aliases`, `serving.bulletin_rules`,
`serving.bulletin_assets`, `serving.document_origins` (every file a document came from, for duplicates), `serving.document_relations` (relations only between documents; callers
must still check `can_see` before showing a related document).

## Guarantees

1. No row is returned for an object without access alternatives.
2. Passage access alternatives include all groups from `restricted_tags`.
3. Passage text contains no unverified OCR value. Withheld values appear as
   `[[unverified:<review_item_id>|page=<n>]]`; the passage's `page_image` gives the image. The
   query feature MUST render this as "value unverified, see scanned page <n>" with a link, and MUST
   NOT replace it with any value.
4. `possibly_stale`, `documents.status = 'superseded'`, and `authority_tier` are always populated
   so the query feature can apply precedence.
5. `bulletin_assets.status = 'check_on_site'` means applicability depends on a condition only
   verifiable at the machine; the condition text is in `bulletin_rules.variant_condition`.
6. The published version changes atomically; a single query never mixes versions.
