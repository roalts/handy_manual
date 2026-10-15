"""Work-order drafts and the audit log (feature 005; specs/contracts/services.md).

    from copilot_workorders import build_services, migrate
    work_orders, audit = build_services(database_url)
"""
import os
import re
from pathlib import Path

import psycopg

from copilot_contracts.services import SubmissionFailed
from copilot_workorders.directory import UsersFile
from copilot_workorders.outbox import FakeOutbox
from copilot_workorders.service import PgAuditLog, PgWorkOrders, _Store

__all__ = ["build_services", "migrate", "PgAuditLog", "PgWorkOrders", "SubmissionFailed"]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL = Path(__file__).parent / "db" / "app_schema.sql"
_IDENT = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def _schema(name: str) -> str:
    """`name` if it is a plain SQL identifier (it is formatted into SQL), else ValueError."""
    if not _IDENT.fullmatch(name):
        raise ValueError(f"invalid schema name {name!r}")
    return name


def _project_path(value: str) -> Path:
    """`value` as a path, a relative one taken from the project root."""
    p = Path(value)
    return p if p.is_absolute() else PROJECT_ROOT / p


def migrate(conn: psycopg.Connection, *, schema: str = "app") -> None:
    """Create or update the schema. Idempotent and safe to run from several processes at once."""
    sql = SCHEMA_SQL.read_text().replace("{schema}", _schema(schema))
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('copilot_workorders.migrate'))")
        conn.execute(sql)


def build_services(database_url: str | None = None, *, schema: str = "app",
                   users_path: Path | None = None,
                   outbox_dir: Path | None = None) -> tuple[PgWorkOrders, PgAuditLog]:
    """Returns (WorkOrders, AuditLog). Call `migrate` once at start before using them."""
    url = database_url or os.environ.get("DATABASE_URL", "postgresql:///copilot")
    users = UsersFile(users_path or _project_path(os.environ.get("USERS_PATH", "users.json")))
    outbox = FakeOutbox(outbox_dir or _project_path(os.environ.get("DATA_DIR", "data")) / "outbox")
    store = _Store(url, _schema(schema), users)
    return PgWorkOrders(store, outbox), PgAuditLog(store)
