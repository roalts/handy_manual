CREATE SCHEMA IF NOT EXISTS control;

CREATE TABLE control.runs (
    run_id          text PRIMARY KEY,
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    dataset_version text,
    outcome         text CHECK (outcome IN ('published', 'validation_failed', 'built', 'error')),
    report_path     text
);

CREATE TABLE control.source_files (
    path            text PRIMARY KEY,
    fingerprint     text,
    size_bytes      bigint,
    source_system   text,
    required_groups text[],
    status          text NOT NULL
                    CHECK (status IN ('active', 'quarantined', 'partial', 'removed')),
    first_seen_run  text,
    last_seen_run   text
);

CREATE TABLE control.quarantine (
    path   text NOT NULL,
    run_id text NOT NULL,
    stage  text NOT NULL,
    reason text NOT NULL CHECK (reason IN ('no_access_rule', 'unknown_group', 'empty_file',
                                           'unreadable', 'unsupported_format')),
    detail text,
    PRIMARY KEY (path, run_id)
);

CREATE TABLE control.review_items (
    item_id    text PRIMARY KEY,
    kind       text NOT NULL CHECK (kind IN ('ocr_value_mismatch', 'metadata_unverified',
                                             'restricted_borderline', 'marker_approval',
                                             'unresolved_link', 'unknown_asset')),
    path       text,
    anchor     jsonb,
    field      text,
    candidates jsonb,
    reason     text,
    status     text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    first_run  text,
    last_run   text
);

CREATE TABLE control.resolutions (
    item_id     text PRIMARY KEY REFERENCES control.review_items (item_id),
    value       jsonb NOT NULL,
    resolved_by text,
    resolved_at timestamptz NOT NULL DEFAULT now(),
    note        text
);

CREATE TABLE control.published (
    singleton       boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    dataset_version text NOT NULL,
    published_at    timestamptz NOT NULL DEFAULT now(),
    run_id          text NOT NULL
);
