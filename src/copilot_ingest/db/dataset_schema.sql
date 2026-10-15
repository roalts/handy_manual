-- Template for one dataset version. {schema} is replaced with ds_NNNN.
CREATE SCHEMA {schema};

CREATE TABLE {schema}.documents (
    doc_id            text PRIMARY KEY,
    title             text,
    doc_type          text NOT NULL,
    authority_tier    int NOT NULL,
    controlled        boolean NOT NULL DEFAULT false,
    models            text[] NOT NULL DEFAULT '{{}}',
    revision          text,
    issue_date        date,
    languages         text[] NOT NULL DEFAULT '{{}}',
    status            text NOT NULL CHECK (status IN ('active', 'superseded', 'partial')),
    missing_pages     int[] NOT NULL DEFAULT '{{}}',
    extractor_version text NOT NULL
);

CREATE TABLE {schema}.document_origins (
    doc_id          text NOT NULL REFERENCES {schema}.documents (doc_id),
    path            text NOT NULL,
    fingerprint     text NOT NULL,
    source_system   text NOT NULL,
    required_groups text[] NOT NULL,
    PRIMARY KEY (doc_id, path)
);

CREATE TABLE {schema}.document_relations (
    from_doc text NOT NULL,
    to_doc   text NOT NULL,
    relation text NOT NULL CHECK (relation IN ('supersedes', 'possibly_stale_vs',
                                               'duplicate_of', 'pairs_language_with')),
    quote    text,
    page     int,
    PRIMARY KEY (from_doc, to_doc, relation)
);

CREATE TABLE {schema}.bulletin_rules (
    rule_id            text PRIMARY KEY,
    doc_id             text NOT NULL,
    model              text NOT NULL,
    serial_from        text,
    serial_to          text,
    firmware_condition text,
    market_condition   text,
    variant_condition  text,
    outcome            text NOT NULL CHECK (outcome IN ('affected', 'in_campaign', 'not_affected')),
    campaign_code      text,
    action_summary     text,
    quote              text NOT NULL,
    page               int
);

CREATE TABLE {schema}.bulletin_assets (
    doc_id   text NOT NULL,
    asset_id text NOT NULL,
    status   text NOT NULL CHECK (status IN ('affected', 'in_campaign', 'not_affected',
                                             'check_on_site')),
    rule_id  text,
    reason   text,
    PRIMARY KEY (doc_id, asset_id)
);

CREATE TABLE {schema}.passages (
    passage_id        text PRIMARY KEY,
    doc_id            text NOT NULL REFERENCES {schema}.documents (doc_id),
    role              text NOT NULL CHECK (role IN ('standard', 'parent', 'child')),
    parent_passage_id text,
    anchor            jsonb NOT NULL,
    heading_path      text[] NOT NULL DEFAULT '{{}}',
    block_types       text[] NOT NULL DEFAULT '{{}}',
    lang              text,
    text_original     text NOT NULL,
    text_en           text,
    fault_codes       text[] NOT NULL DEFAULT '{{}}',
    part_numbers      text[] NOT NULL DEFAULT '{{}}',
    asset_ids         text[] NOT NULL DEFAULT '{{}}',
    serials           text[] NOT NULL DEFAULT '{{}}',
    case_numbers      text[] NOT NULL DEFAULT '{{}}',
    models            text[] NOT NULL DEFAULT '{{}}',
    restricted_tags   text[] NOT NULL DEFAULT '{{}}',
    ocr               text NOT NULL DEFAULT 'none'
                      CHECK (ocr IN ('none', 'verified', 'has_withheld_values')),
    page_image        text,
    possibly_stale    boolean NOT NULL DEFAULT false,
    tsv               tsvector,
    embedding         vector(1024),
    fingerprint       text NOT NULL,
    extractor_version text NOT NULL,
    ingested_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ON {schema}.passages USING gin (tsv);
CREATE INDEX ON {schema}.passages USING gin (fault_codes);
CREATE INDEX ON {schema}.passages USING gin (part_numbers);
CREATE INDEX ON {schema}.passages USING gin (asset_ids);
CREATE INDEX ON {schema}.passages USING gin (serials);
CREATE INDEX ON {schema}.passages USING gin (case_numbers);
CREATE INDEX ON {schema}.passages (doc_id);

CREATE TABLE {schema}.access_alternatives (
    object_type     text NOT NULL CHECK (object_type IN ('document', 'passage', 'event')),
    object_id       text NOT NULL,
    alt_no          int NOT NULL,
    required_groups text[] NOT NULL,
    PRIMARY KEY (object_type, object_id, alt_no)
);

CREATE TABLE {schema}.assets (
    asset_id     text PRIMARY KEY,
    model        text NOT NULL,
    serial       text NOT NULL,
    site         text NOT NULL,
    site_name    text,
    customer     text,
    region       text NOT NULL,
    install_date date,
    firmware     text,
    oil_type     text,
    contract_end date
);

CREATE TABLE {schema}.asset_aliases (
    alias    text PRIMARY KEY,
    asset_id text NOT NULL,
    source   text NOT NULL
);

CREATE TABLE {schema}.site_aliases (
    alias text PRIMARY KEY,
    site  text NOT NULL
);

CREATE TABLE {schema}.service_events (
    event_id       text PRIMARY KEY,
    asset_id       text NOT NULL,
    event_date     date NOT NULL,
    event_type     text NOT NULL CHECK (event_type IN ('inspection', 'preventive', 'corrective',
                                                       'alarm', 'firmware', 'meter',
                                                       'fgas_check', 'case')),
    fault_code     text,
    status         text NOT NULL CHECK (status IN ('completed', 'open', 'cancelled')),
    notes_original text,
    notes_en       text,
    parts          text[] NOT NULL DEFAULT '{{}}',
    labor_hours    numeric,
    run_hours      numeric,
    technician     text,
    sources        jsonb NOT NULL,
    passage_id     text
);

CREATE INDEX ON {schema}.service_events (asset_id, event_date);

CREATE TABLE {schema}.dataset_info (
    singleton       boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    embedding_model text,
    embedding_dims  int,
    built_at        timestamptz NOT NULL DEFAULT now()
);

-- Content markers of restricted procedures, for server-side leak guards only; never shown.
CREATE TABLE {schema}.restricted_markers (
    procedure text NOT NULL,
    marker    text NOT NULL,
    status    text NOT NULL CHECK (status IN ('approved', 'proposed')),
    PRIMARY KEY (procedure, marker)
);
