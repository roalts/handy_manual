"""The work-order endpoints and audit over the real `copilot_workorders` (005), through HTTP.

Each test uses its own scratch schema (dropped afterwards), a copy of users.json and a temporary
outbox; corpus data and visibility come from the real `serving` schema.
"""
import json
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from copilot_api import Deps, create_app
from copilot_api.engines import EnginePool
from copilot_api.identity import Directory
from copilot_api.session import Sessions
from copilot_api.sources import SourceStore
from tests.api.fakes import FakeEngine, example

pytestmark = [pytest.mark.integration]

workorders = pytest.importorskip("copilot_workorders")

SUGGESTION = example("restricted").work_order_suggestion.model_dump(mode="json")
"""E-31 (compressor drive overcurrent fault) on TAC-C-0143 (Tacoma VRS-110), needs cert-hv."""
NK600_84 = "p_89e01fa9f9431d888616bfd8"
"""NK-600 chiller manual 8.4 recovery and recharge, tagged SOP-020 (restricted)."""


class Env:
    def __init__(self, config, db, tmp_path):
        self.db = db
        self.schema = f"wo_test_{uuid.uuid4().hex[:12]}"
        workorders.migrate(db, schema=self.schema)
        self.outbox = tmp_path / "outbox"
        wo, audit = workorders.build_services(config.database_url, schema=self.schema,
                                              users_path=config.users_path,
                                              outbox_dir=self.outbox)
        directory = Directory(config.users_path)
        sources = SourceStore(config.database_url, config.corpus_dir, config.data_dir,
                              known_groups=lambda: directory.groups().keys())
        self.sessions = Sessions(config.session_secret, config.session_max_age)
        self.app = create_app(Deps(
            config=config, directory=directory, sessions=self.sessions,
            engines=EnginePool(lambda: FakeEngine(example("restricted")), 1), sources=sources,
            work_orders=wo, audit=audit))

    def client(self, user_id):
        c = TestClient(self.app, raise_server_exceptions=False)
        c.cookies.set("copilot_session", self.sessions.sign(user_id))
        return c

    def events(self, kind=None):
        rows = self.db.execute(
            f"SELECT kind, user_id, outcome, passage_ids FROM {self.schema}.audit_events"
            " ORDER BY seq").fetchall()
        return [r for r in rows if kind is None or r[0] == kind]

    def outbox_files(self):
        return sorted(p.name for p in self.outbox.rglob("*") if p.is_file())


@pytest.fixture
def env(config, tmp_path):
    try:
        db = psycopg.connect(config.database_url, autocommit=True)
    except psycopg.OperationalError as e:
        pytest.skip(f"database not available: {e}")
    if db.execute("SELECT to_regnamespace('serving')").fetchone()[0] is None:
        pytest.skip("no published dataset")
    e = Env(config, db, tmp_path)
    try:
        yield e
    finally:
        db.execute(f"DROP SCHEMA {e.schema} CASCADE")
        db.close()


def test_restricted_flow_end_to_end(env):
    """u03 asks, drafts, requests approval; u12 and u07 can't see it; u08 approves; u03 submits
    once to MaintPro (same key, same reference, one outbox file)."""
    tech = env.client("u03")
    answer = tech.post("/api/ask", json={"question": "E-31 on TAC-C-0143, how do I reset it?"})
    assert answer.status_code == 200
    r = tech.post("/api/work-orders", json={"answer_id": answer.json()["answer_id"],
                                            "suggestion": SUGGESTION})
    assert r.status_code == 201, r.text
    d = r.json()
    assert (d["target_system"], d["eligible_approvers"]) == ("maintpro", ["u08"])
    base = f"/api/work-orders/{d['draft_id']}"

    assert env.client("u12").get(base).status_code == 403
    assert env.client("u07").get(base).status_code == 403
    assert env.client("u12").get("/api/work-orders").json() == []

    bad = tech.post(f"{base}/submit", json={"confirm": False},
                    headers={"Idempotency-Key": d["idempotency_key"]})
    assert bad.status_code == 422
    assert tech.post(f"{base}/request-approval").json()["status"] == "pending_approval"
    assert tech.post(f"{base}/approve", json={"note": "me"}).status_code == 403
    r = env.client("u08").post(f"{base}/approve", json={"note": "Booked for Thursday"})
    assert (r.status_code, r.json()["decision_note"]) == (200, "Booked for Thursday")

    key = {"Idempotency-Key": d["idempotency_key"]}
    first = tech.post(f"{base}/submit", json={"confirm": True}, headers=key)
    again = tech.post(f"{base}/submit", json={"confirm": True}, headers=key)
    assert first.status_code == again.status_code == 200, first.text
    assert first.json()["external_ref"] == again.json()["external_ref"]
    assert first.json()["external_ref"].startswith("MP-")
    assert len(env.outbox_files()) == 1

    kinds = [e[0] for e in env.events()]
    assert kinds[0] == "answer"
    assert {"draft_created", "draft_approved", "draft_submitted", "access_denied"} <= set(kinds)
    assert env.events("answer")[0][3] == ["p_f305f74b3d432a456bfd9221"]


def test_eu_sop020_draft_has_no_eligible_approver(env):
    """u05 (EU refrigeration engineer) drafts from an SOP-020 passage; u07 (EU team lead without
    refrigerant certification) can't see it, so no one can approve."""
    c = env.client("u05")
    r = c.post("/api/work-orders", json={"suggestion": {
        "asset_id": "RTM-H-0007", "summary": "L-03 low suction, recover and recharge",
        "fault_code": "L-03", "citations": [NK600_84]}})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["target_system"] == "servio"
    assert "cert-refrigerant" in d["required_certification"]
    assert "no eligible approver" in d["approval_reasons"]
    assert d["eligible_approvers"] == []
    assert env.client("u07").get(f"/api/work-orders/{d['draft_id']}").status_code == 403
    r = c.post(f"/api/work-orders/{d['draft_id']}/request-approval")
    assert (r.status_code, r.json()["error"]) == (409, "invalid_state")


def test_source_events_go_to_the_real_audit_log(env):
    c = env.client("u06")
    assert c.get("/api/sources/p_f71b980da8173a0d23371f8c").status_code == 200
    assert c.get(f"/api/sources/{NK600_84}").status_code == 403
    assert [(e[0], e[1], e[2]) for e in env.events()] == [
        ("source_view", "u06", "shown"), ("access_denied", "u06", "not_visible")]


def test_unknown_patch_field_and_citations(env):
    c = env.client("u03")
    d = c.post("/api/work-orders", json={"suggestion": SUGGESTION}).json()
    for body in ({"citations": []}, {"status": "approved"}):
        r = c.patch(f"/api/work-orders/{d['draft_id']}", json=body)
        assert (r.status_code, r.json()["error"]) == (422, "invalid_request")
    r = c.patch(f"/api/work-orders/{d['draft_id']}", json={"priority": "high"})
    assert (r.status_code, r.json()["priority"]) == (200, "high")
    r = c.patch(f"/api/work-orders/{d['draft_id']}",
                json={"needs_specialist": True, "return_visit": True})
    assert r.status_code == 200, r.text
    assert {"specialist", "return visit"} <= set(r.json()["approval_reasons"])


def test_users_json_change_hides_draft(env, config):
    c = env.client("u03")
    d = c.post("/api/work-orders", json={"suggestion": SUGGESTION}).json()
    data = json.loads(config.users_path.read_text())
    next(u for u in data["users"] if u["id"] == "u03")["groups"] = ["region-na"]
    config.users_path.write_text(json.dumps(data))
    assert c.get(f"/api/work-orders/{d['draft_id']}").status_code == 403
