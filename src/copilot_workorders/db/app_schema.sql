-- Work-order drafts and the audit log (specs/contracts/work-orders-audit.md, services.md).
-- Applied idempotently by copilot_workorders.migrate(conn); {schema} is "app" outside tests.

CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE IF NOT EXISTS {schema}.drafts (
    draft_id               text PRIMARY KEY,
    created_by             text NOT NULL,
    created_at             timestamptz NOT NULL,
    updated_at             timestamptz NOT NULL,
    answer_id              text,
    asset_id               text NOT NULL,
    region                 text NOT NULL CHECK (region IN ('NA', 'EU')),
    target_system          text NOT NULL CHECK (target_system IN ('maintpro', 'servio')),
    fault_code             text,
    summary                text NOT NULL CHECK (summary <> ''),
    work_steps             text NOT NULL DEFAULT '',
    required_certification text[] NOT NULL DEFAULT '{}',
    parts                  jsonb NOT NULL DEFAULT '[]',
    campaign_code          text,
    priority               text NOT NULL DEFAULT 'medium'
                           CHECK (priority IN ('low', 'medium', 'high')),
    citations              text[] NOT NULL DEFAULT '{}',
    status                 text NOT NULL DEFAULT 'draft'
                           CHECK (status IN ('draft', 'pending_approval', 'approved', 'rejected',
                                             'submitted')),
    decided_by             text,
    decided_at             timestamptz,
    decision_note          text,
    idempotency_key        text NOT NULL UNIQUE,
    external_ref           text,
    submitted_by           text,
    submitted_at           timestamptz,
    CHECK ((status = 'submitted') = (external_ref IS NOT NULL))
);

ALTER TABLE {schema}.drafts
    ADD COLUMN IF NOT EXISTS needs_specialist boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS return_visit boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS drafts_created_by ON {schema}.drafts (created_by);
CREATE INDEX IF NOT EXISTS drafts_region ON {schema}.drafts (region);

CREATE TABLE IF NOT EXISTS {schema}.audit_events (
    seq             bigserial UNIQUE,
    event_id        text PRIMARY KEY,
    at              timestamptz NOT NULL,
    user_id         text NOT NULL,
    kind            text NOT NULL,
    answer_id       text,
    draft_id        text,
    dataset_version text,
    passage_ids     text[] NOT NULL DEFAULT '{}',
    outcome         text NOT NULL,
    details         jsonb NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS audit_events_answer ON {schema}.audit_events (answer_id);
CREATE INDEX IF NOT EXISTS audit_events_draft ON {schema}.audit_events (draft_id);
CREATE INDEX IF NOT EXISTS audit_events_user ON {schema}.audit_events (user_id);

CREATE OR REPLACE FUNCTION {schema}.audit_events_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only (% refused)', TG_OP;
END
$$;

CREATE OR REPLACE TRIGGER audit_events_no_change
    BEFORE UPDATE OR DELETE ON {schema}.audit_events
    FOR EACH ROW EXECUTE FUNCTION {schema}.audit_events_append_only();

CREATE OR REPLACE TRIGGER audit_events_no_truncate
    BEFORE TRUNCATE ON {schema}.audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION {schema}.audit_events_append_only();

REVOKE UPDATE, DELETE, TRUNCATE ON {schema}.audit_events FROM PUBLIC;
