from copilot_ingest.db.repo import DB_DIR, dataset_versions, published_version

KEEP_VERSIONS = 3


class PublishRefused(RuntimeError):
    pass


def publish(conn, schema: str, run_id: str, validation_passed: bool) -> None:
    """Point the serving schema at `schema` in one transaction."""
    if not validation_passed:
        raise PublishRefused(f"{schema} did not pass validation")
    if schema not in dataset_versions(conn):
        raise PublishRefused(f"{schema} does not exist")
    with conn.transaction():
        conn.execute("DROP SCHEMA IF EXISTS serving CASCADE")
        # versions built before dataset_info existed stay publishable (rollback)
        conn.execute(f"CREATE TABLE IF NOT EXISTS {schema}.dataset_info (singleton boolean"
                     " PRIMARY KEY DEFAULT true CHECK (singleton), embedding_model text,"
                     " embedding_dims int, built_at timestamptz NOT NULL DEFAULT now())")
        conn.execute(f"CREATE TABLE IF NOT EXISTS {schema}.restricted_markers (procedure text"
                     " NOT NULL, marker text NOT NULL, status text NOT NULL, PRIMARY KEY"
                     " (procedure, marker))")
        conn.execute((DB_DIR / "serving.sql").read_text().replace("{schema}", schema))
        conn.execute(
            "INSERT INTO control.published (singleton, dataset_version, run_id)"
            " VALUES (true, %s, %s) ON CONFLICT (singleton) DO UPDATE SET"
            " dataset_version = EXCLUDED.dataset_version, run_id = EXCLUDED.run_id,"
            " published_at = now()", (schema, run_id))


def prune(conn) -> list[str]:
    """Keep the serving version, the last KEEP_VERSIONS published versions (rollback targets),
    and the newest version (to inspect a failed build). Drop the rest."""
    existing = dataset_versions(conn)
    published = [r[0] for r in conn.execute(
        "SELECT dataset_version FROM control.runs WHERE outcome = 'published'"
        " AND dataset_version IS NOT NULL ORDER BY started_at DESC")]
    keep = set(list(dict.fromkeys(v for v in published if v in existing))[:KEEP_VERSIONS])
    current = published_version(conn)
    if current:
        keep.add(current)
    if existing:
        keep.add(existing[-1])
    dropped = []
    for v in dataset_versions(conn):
        if v not in keep:
            conn.execute(f"DROP SCHEMA {v} CASCADE")
            dropped.append(v)
    conn.commit()
    return dropped
