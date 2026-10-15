from contextlib import contextmanager
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from copilot_ingest.settings import get_settings

DB_DIR = Path(__file__).parent
MIGRATIONS_DIR = DB_DIR / "migrations"


@contextmanager
def connect(autocommit: bool = False):
    """Database connection with pgvector types registered when the extension exists."""
    with psycopg.connect(get_settings().database_url, autocommit=autocommit) as conn:
        try:
            register_vector(conn)
        except psycopg.ProgrammingError:
            pass  # vector extension not installed yet (before migration 002)
        yield conn


def migrate() -> list[str]:
    """Apply pending migrations in order; returns the names applied."""
    applied: list[str] = []
    with connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS public.schema_migrations "
            "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {r[0] for r in conn.execute("SELECT name FROM public.schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            conn.execute(path.read_text())
            conn.execute("INSERT INTO public.schema_migrations (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
        conn.commit()
    return applied


def dataset_versions(conn) -> list[str]:
    """Existing dataset version schemas (ds_0001 = dataset version 1, ...), oldest first."""
    rows = conn.execute(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name ~ '^ds_[0-9]{4}$' ORDER BY schema_name"
    ).fetchall()
    return [r[0] for r in rows]


def create_dataset_version(conn) -> str:
    """Create the next dataset version schema from `dataset_schema.sql`; returns its name.
    Numbering follows the highest existing schema, not the published one."""
    existing = dataset_versions(conn)
    n = int(existing[-1][3:]) + 1 if existing else 1
    schema = f"ds_{n:04d}"
    conn.execute((DB_DIR / "dataset_schema.sql").read_text().format(schema=schema))
    return schema


def published_version(conn) -> str | None:
    """Dataset version serving currently points at, or None if nothing is published."""
    row = conn.execute("SELECT dataset_version FROM control.published").fetchone()
    return row[0] if row else None
