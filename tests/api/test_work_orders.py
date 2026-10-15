"""Work-order endpoints over HTTP (003 spec US4; http-api.md Work orders).

The rules belong to 005; these tests check the HTTP side: status codes, error bodies, the
confirm and Idempotency-Key checks done by the API, and access-denied audit events.
"""
import pytest

from copilot_contracts import WorkOrderDraft
from tests.api.fakes import example

SUGGESTION = example("restricted").work_order_suggestion.model_dump(mode="json")
"""E-31 (compressor drive overcurrent fault) on TAC-C-0143 (Tacoma VRS-110), needs cert-hv."""


def _create(client, **extra):
    r = client.post("/api/work-orders", json={"answer_id": "ans_1", "suggestion": SUGGESTION,
                                              **extra})
    assert r.status_code == 201, r.text
    return WorkOrderDraft.model_validate(r.json())


def test_create_returns_201_draft(harness):
    d = _create(harness.client("u03"))
    assert (d.created_by, d.asset_id, d.target_system, d.status) == (
        "u03", "TAC-C-0143", "maintpro", "draft")
    assert d.required_certification == ["cert-hv"]
    assert d.eligible_approvers == ["u08"]
    assert [e.kind for e in harness.events()] == ["draft_created"]


def test_draft_of_another_family_is_403(harness):
    """u12 (NA conveyor technician) asks for u03's compressor draft."""
    d = _create(harness.client("u03"))
    r = harness.client("u12").get(f"/api/work-orders/{d.draft_id}")
    assert r.status_code == 403
    assert r.json()["error"] == "not_visible"
    denied = harness.events("access_denied")
    assert [(e.user_id, e.draft_id) for e in denied] == [("u12", d.draft_id)]
    assert harness.client("u12").get("/api/work-orders").json() == []


def test_unknown_draft_is_404(harness):
    r = harness.client("u03").get("/api/work-orders/wo_missing")
    assert (r.status_code, r.json()["error"]) == (404, "not_found")


@pytest.mark.parametrize(("body", "headers"), [
    ({}, {"Idempotency-Key": "k-1"}),
    ({"confirm": False}, {"Idempotency-Key": "k-1"}),
    ({"confirm": "true"}, {"Idempotency-Key": "k-1"}),
    ({"confirm": True}, {}),
    ({"confirm": True}, {"Idempotency-Key": "  "}),
])
def test_submit_needs_confirm_and_key(make_harness, body, headers):
    h = make_harness()
    c = h.client("u03")
    d = _create(c, suggestion={**SUGGESTION, "required_certification": []})
    assert d.approval_reasons == []
    r = c.post(f"/api/work-orders/{d.draft_id}/submit", json=body, headers=headers)
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_request"
    assert c.get(f"/api/work-orders/{d.draft_id}").json()["status"] == "draft"
    assert h.work_orders.submissions == {}
    assert not h.events("draft_submitted")


def test_full_approval_round_trip_and_idempotent_submit(harness):
    tech, lead = harness.client("u03"), harness.client("u08")
    d = _create(tech)
    base = f"/api/work-orders/{d.draft_id}"

    r = tech.post(f"{base}/submit", json={"confirm": True}, headers={"Idempotency-Key": "k"})
    assert (r.status_code, r.json()["error"]) == (409, "invalid_state")

    assert tech.post(f"{base}/request-approval").json()["status"] == "pending_approval"
    r = tech.post(f"{base}/approve", json={"note": "self"})
    assert (r.status_code, r.json()["error"]) == (403, "forbidden")
    assert tech.patch(base, json={"summary": "x"}).json()["error"] == "not_editable"

    r = lead.post(f"{base}/approve", json={"note": "Go ahead"})
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["decision_note"], r.json()["decided_by"]) == (
        "approved", "Go ahead", "u08")

    key = {"Idempotency-Key": d.idempotency_key}
    first = tech.post(f"{base}/submit", json={"confirm": True}, headers=key)
    again = tech.post(f"{base}/submit", json={"confirm": True}, headers=key)
    assert first.status_code == again.status_code == 200
    assert first.json()["external_ref"].startswith("MP-")
    assert first.json() == again.json()
    assert len(harness.events("draft_submitted")) == 1


def test_reject_with_note_then_edit(harness):
    tech, lead = harness.client("u03"), harness.client("u08")
    d = _create(tech)
    base = f"/api/work-orders/{d.draft_id}"
    tech.post(f"{base}/request-approval")
    r = lead.post(f"{base}/reject", json={"note": "Add the part"})
    assert (r.json()["status"], r.json()["decision_note"]) == ("rejected", "Add the part")
    r = tech.patch(base, json={"parts": [{"part_number": "41-2207", "quantity": 2}],
                               "priority": "high"})
    assert r.status_code == 200
    assert r.json()["status"] == "draft"
    assert r.json()["parts"] == [{"part_number": "41-2207", "quantity": 2}]


@pytest.mark.parametrize("body", [{"status": "approved"}, {"citations": []},
                                  {"required_certification": []}, {"external_ref": "MP-1"},
                                  {}, {"parts": "41-2207"}, {"parts": [{"quantity": 1}]}])
def test_patch_rejects_non_editable_or_bad_fields(harness, body):
    c = harness.client("u03")
    d = _create(c)
    r = c.patch(f"/api/work-orders/{d.draft_id}", json=body)
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_request"


def test_patch_specialist_and_return_visit(harness):
    c = harness.client("u03")
    d = _create(c, suggestion={**SUGGESTION, "required_certification": []})
    r = c.patch(f"/api/work-orders/{d.draft_id}",
                json={"needs_specialist": True, "return_visit": True})
    assert r.status_code == 200
    body = r.json()
    assert (body["needs_specialist"], body["return_visit"]) == (True, True)
    assert {"specialist", "return visit"} <= set(body["approval_reasons"])
    bad = c.patch(f"/api/work-orders/{d.draft_id}", json={"return_visit": "yes"})
    assert (bad.status_code, bad.json()["error"]) == (422, "invalid_request")


def test_patch_citations_is_refused(harness):
    c = harness.client("u03")
    d = _create(c)
    r = c.patch(f"/api/work-orders/{d.draft_id}", json={"citations": []})
    assert (r.status_code, r.json()["error"]) == (422, "invalid_request")
    assert c.get(f"/api/work-orders/{d.draft_id}").json()["citations"] == d.citations


def test_submission_failed_maps_to_503(harness, monkeypatch):
    from copilot_contracts.services import SubmissionFailed

    c = harness.client("u03")
    d = _create(c, suggestion={**SUGGESTION, "required_certification": []})

    def fail(*a, **kw):
        raise SubmissionFailed("outbox not writable")

    monkeypatch.setattr(harness.work_orders, "submit", fail)
    r = c.post(f"/api/work-orders/{d.draft_id}/submit", json={"confirm": True},
               headers={"Idempotency-Key": d.idempotency_key})
    assert r.status_code == 503
    assert r.json() == {"error": "submission_failed", "detail": "outbox not writable"}
    assert r.headers["cache-control"] == "no-store"


def test_create_validation(harness):
    c = harness.client("u03")
    assert c.post("/api/work-orders", json={"suggestion": {"asset_id": "TAC-C-0143"}}
                  ).status_code == 422
    assert c.post("/api/work-orders", json={"suggestion": SUGGESTION, "status": "approved"}
                  ).status_code == 422
    no_asset = {**SUGGESTION, "asset_id": None}
    assert c.post("/api/work-orders", json={"suggestion": no_asset}).status_code == 422
    d = _create(c, suggestion=no_asset, asset_id="TAC-C-0142")
    assert d.asset_id == "TAC-C-0142"


def test_mine_filter(harness):
    _create(harness.client("u03"))
    assert len(harness.client("u03").get("/api/work-orders?mine=true").json()) == 1
    lead = harness.client("u08")
    assert len(lead.get("/api/work-orders").json()) == 1
    assert lead.get("/api/work-orders?mine=true").json() == []
