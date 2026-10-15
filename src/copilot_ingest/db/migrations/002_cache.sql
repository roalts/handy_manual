CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS cache;

CREATE TABLE cache.model_calls (
    key            text PRIMARY KEY,
    provider       text NOT NULL,
    model          text NOT NULL,
    prompt_version text NOT NULL,
    input_hash     text NOT NULL,
    output         jsonb NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE cache.embeddings (
    text_hash  text NOT NULL,
    model      text NOT NULL,
    dims       int NOT NULL,
    embedding  vector(1024) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (text_hash, model)
);
