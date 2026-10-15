"""Every database test runs in its own scratch schema, dropped afterwards; `app` is never touched.

Corpus data comes from the real published `serving` schema. The outbox and a copy of users.json
live in the test's tmp_path, so tests can change a user's groups without touching the real file.
"""
import json
import os
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.rows import dict_row

from copilot_contracts.answer import Identity, WorkOrderSuggestion
from copilot_workorders import build_services, migrate

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///copilot")

E31_PASSAGE = "p_f305f74b3d432a456bfd9221"
"""Compressor playbook, E-31 drive overcurrent: says the reset is HV-PROC-07, no steps."""
NK600_SOP020_PASSAGE = "p_89e01fa9f9431d888616bfd8"
"""NK-600 manual 8.4 recovery and recharge, tagged SOP-020; visible to u05 and u11, not u07."""


def restricted_suggestion() -> WorkOrderSuggestion:
    example = json.loads((ROOT / "specs/contracts/examples/restricted.json").read_text())
    return WorkOrderSuggestion.model_validate(example["work_order_suggestion"])


@pytest.fixture
def db():
    try:
        conn = psycopg.connect(DATABASE_URL, autocommit=True)
    except psycopg.OperationalError as e:
        pytest.skip(f"database not available: {e}")
    if conn.execute("SELECT to_regnamespace('serving')").fetchone()[0] is None:
        pytest.skip("no published dataset")
    yield conn
    conn.close()


@pytest.fixture
def env(db, tmp_path):
    schema = f"wo_test_{uuid.uuid4().hex[:12]}"
    migrate(db, schema=schema)
    users = tmp_path / "users.json"
    shutil.copy(ROOT / "users.json", users)
    outbox = tmp_path / "outbox"
    wo, audit = build_services(DATABASE_URL, schema=schema, users_path=users, outbox_dir=outbox)

    def who(user_id: str) -> Identity:
        u = next(u for u in json.loads(users.read_text())["users"] if u["id"] == user_id)
        return Identity(user_id=u["id"], name=u["name"], groups=frozenset(u["groups"]))

    def set_groups(user_id: str, groups: list[str]) -> None:
        data = json.loads(users.read_text())
        found = [u for u in data["users"] if u["id"] == user_id]
        if found:
            found[0]["groups"] = groups
        else:
            data["users"].append({"id": user_id, "name": user_id, "title": "test",
                                  "groups": groups})
        users.write_text(json.dumps(data))

    def events(**filters):
        where = " AND ".join(f"{k} = %s" for k in filters) or "true"
        return db.cursor(row_factory=dict_row).execute(
            f"SELECT kind, user_id, outcome, details, passage_ids FROM {schema}.audit_events"
            f" WHERE {where} ORDER BY seq", list(filters.values())).fetchall()

    def outbox_files():
        return sorted(p.relative_to(outbox).as_posix() for p in outbox.rglob("*") if p.is_file())

    try:
        yield SimpleNamespace(db=db, schema=schema, wo=wo, audit=audit, who=who,
                              set_groups=set_groups, events=events, outbox=outbox,
                              outbox_files=outbox_files)
    finally:
        db.execute(f"DROP SCHEMA {schema} CASCADE")
