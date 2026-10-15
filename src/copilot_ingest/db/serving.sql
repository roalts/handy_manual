-- Serving contract (contracts/serving.md). {schema} is replaced with the published ds_NNNN.
-- Every function filters by access alternatives before ranking; an object with no alternatives
-- is invisible.
CREATE SCHEMA serving;

CREATE FUNCTION serving.can_see(p_object_type text, p_object_id text, p_groups text[])
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1 FROM {schema}.access_alternatives a
        WHERE a.object_type = p_object_type
          AND a.object_id = p_object_id
          AND a.required_groups <@ p_groups
    )
$$;

CREATE FUNCTION serving.passages_for(p_groups text[])
RETURNS SETOF {schema}.passages LANGUAGE sql STABLE AS $$
    SELECT p.* FROM {schema}.passages p
    WHERE EXISTS (
        SELECT 1 FROM {schema}.access_alternatives a
        WHERE a.object_type = 'passage' AND a.object_id = p.passage_id
          AND a.required_groups <@ p_groups
    )
$$;

CREATE FUNCTION serving.events_for(p_groups text[])
RETURNS SETOF {schema}.service_events LANGUAGE sql STABLE AS $$
    SELECT e.* FROM {schema}.service_events e
    WHERE EXISTS (
        SELECT 1 FROM {schema}.access_alternatives a
        WHERE a.object_type = 'event' AND a.object_id = e.event_id
          AND a.required_groups <@ p_groups
    )
$$;

CREATE FUNCTION serving.documents_for(p_groups text[])
RETURNS SETOF {schema}.documents LANGUAGE sql STABLE AS $$
    SELECT d.* FROM {schema}.documents d
    WHERE EXISTS (
        SELECT 1 FROM {schema}.access_alternatives a
        WHERE a.object_type = 'document' AND a.object_id = d.doc_id
          AND a.required_groups <@ p_groups
    )
$$;

CREATE FUNCTION serving.keyword_search(p_groups text[], p_query text, p_k int)
RETURNS TABLE (passage_id text, score real) LANGUAGE sql STABLE AS $$
    SELECT p.passage_id, ts_rank(p.tsv, q) AS score
    FROM serving.passages_for(p_groups) p, websearch_to_tsquery('simple', p_query) q
    WHERE p.tsv @@ q
    ORDER BY score DESC
    LIMIT p_k
$$;

CREATE FUNCTION serving.vector_search(p_groups text[], p_embedding vector(1024), p_k int)
RETURNS TABLE (passage_id text, distance double precision) LANGUAGE sql STABLE AS $$
    SELECT p.passage_id, p.embedding <=> p_embedding AS distance
    FROM serving.passages_for(p_groups) p
    WHERE p.embedding IS NOT NULL
    ORDER BY distance
    LIMIT p_k
$$;

CREATE FUNCTION serving.identifier_search(p_groups text[], p_ids text[], p_k int)
RETURNS TABLE (passage_id text, matches int) LANGUAGE sql STABLE AS $$
    SELECT p.passage_id,
           cardinality(ARRAY(SELECT unnest(p.fault_codes || p.part_numbers || p.asset_ids
                                           || p.serials || p.case_numbers || p.models)
                             INTERSECT SELECT unnest(p_ids))) AS matches
    FROM serving.passages_for(p_groups) p
    WHERE p.fault_codes && p_ids OR p.part_numbers && p_ids OR p.asset_ids && p_ids
       OR p.serials && p_ids OR p.case_numbers && p_ids OR p.models && p_ids
    ORDER BY matches DESC, p.passage_id
    LIMIT p_k
$$;

CREATE VIEW serving.assets AS SELECT * FROM {schema}.assets;
CREATE VIEW serving.asset_aliases AS SELECT * FROM {schema}.asset_aliases;
CREATE VIEW serving.site_aliases AS SELECT * FROM {schema}.site_aliases;
CREATE VIEW serving.bulletin_rules AS SELECT * FROM {schema}.bulletin_rules;
CREATE VIEW serving.bulletin_assets AS SELECT * FROM {schema}.bulletin_assets;
CREATE VIEW serving.document_relations AS SELECT * FROM {schema}.document_relations;
CREATE VIEW serving.document_origins AS SELECT * FROM {schema}.document_origins;

-- Names of certification-restricted procedures, never their content (serving-additions.md).
-- One row per access alternative of the procedure document.
CREATE VIEW serving.restricted_procedures AS
    SELECT split_part(d.title, ' ', 1) AS name, d.title, d.doc_id, a.alt_no, a.required_groups
    FROM {schema}.documents d
    JOIN {schema}.access_alternatives a ON a.object_type = 'document' AND a.object_id = d.doc_id
    WHERE d.controlled
      AND EXISTS (SELECT 1 FROM {schema}.access_alternatives c
                  WHERE c.object_type = 'document' AND c.object_id = d.doc_id
                    AND EXISTS (SELECT 1 FROM unnest(c.required_groups) g WHERE g LIKE 'cert-%'));

CREATE FUNCTION serving.page_fully_visible(p_groups text[], p_doc_id text, p_page int)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT NOT EXISTS (
        SELECT 1 FROM {schema}.passages p
        WHERE p.doc_id = p_doc_id
          AND (p.anchor ->> 'page')::int <= p_page
          AND coalesce((p.anchor ->> 'page_end')::int, (p.anchor ->> 'page')::int) >= p_page
          AND NOT serving.can_see('passage', p.passage_id, p_groups)
    ) AND serving.can_see('document', p_doc_id, p_groups)
$$;

CREATE FUNCTION serving.dataset_info()
RETURNS TABLE (dataset_version text, published_at timestamptz, embedding_model text,
               embedding_dims int) LANGUAGE sql STABLE AS $$
    SELECT '{schema}'::text, p.published_at, i.embedding_model, i.embedding_dims
    FROM control.published p LEFT JOIN {schema}.dataset_info i ON true
$$;

-- Leak guards only (serving-additions.md): never send these to a model or a client.
CREATE VIEW serving.restricted_markers AS SELECT * FROM {schema}.restricted_markers;

CREATE FUNCTION serving.hidden_exists(p_groups text[], p_ids text[],
                                      p_embedding vector(1024) DEFAULT NULL,
                                      p_max_distance double precision DEFAULT NULL)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1 FROM {schema}.passages p
        WHERE (p.fault_codes && p_ids OR p.part_numbers && p_ids OR p.asset_ids && p_ids
               OR p.serials && p_ids OR p.case_numbers && p_ids OR p.models && p_ids)
          AND (p_embedding IS NULL OR (p.embedding IS NOT NULL
               AND p.embedding <=> p_embedding <= p_max_distance))
          AND NOT serving.can_see('passage', p.passage_id, p_groups)
    )
$$;
