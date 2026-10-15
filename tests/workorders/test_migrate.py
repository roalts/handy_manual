import psycopg

from copilot_workorders import migrate

from .conftest import DATABASE_URL


def test_migrate_is_idempotent(env):
    migrate(env.db, schema=env.schema)
    migrate(env.db, schema=env.schema)
    tables = {r[0] for r in env.db.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
        [env.schema]).fetchall()}
    assert tables == {"drafts", "audit_events"}


def test_migrate_adds_columns_to_an_earlier_drafts_table(env):
    env.db.execute(f"ALTER TABLE {env.schema}.drafts DROP COLUMN needs_specialist,"
                   " DROP COLUMN return_visit")
    migrate(env.db, schema=env.schema)
    cols = {r[0] for r in env.db.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = 'drafts'", [env.schema]).fetchall()}
    assert {"needs_specialist", "return_visit"} <= cols


def test_migrate_default_app_schema_inside_a_rolled_back_transaction(db):
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("SELECT 1")
        migrate(conn)
        assert conn.execute("SELECT to_regclass('app.audit_events')").fetchone()[0] is not None
        conn.rollback()
