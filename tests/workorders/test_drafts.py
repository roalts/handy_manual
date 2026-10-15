"""Acceptance scenarios of specs/005-work-order-drafts/spec.md against the real serving schema."""
import json
import threading

import pytest

from copilot_contracts.answer import WorkOrderSuggestion
from copilot_contracts.services import (
    Forbidden,
    InvalidRequest,
    InvalidState,
    NotEditable,
    NotFound,
    NotVisible,
    SubmissionFailed,
)

from .conftest import E31_PASSAGE, NK600_SOP020_PASSAGE, restricted_suggestion

pytestmark = pytest.mark.acl


def e31_draft(env, **edits):
    return env.wo.create(env.who("u03"), "ans_example_q06", restricted_suggestion(), **edits)


def approved_e31(env):
    d = e31_draft(env)
    env.wo.request_approval(env.who("u03"), d.draft_id)
    return env.wo.approve(env.who("u08"), d.draft_id, "ok, Kenji takes it Thursday")


def sop020_draft(env):
    """u05's draft for RTM-H-0007 (Rotterdam NK-600 chiller) citing the SOP-020 passage."""
    s = WorkOrderSuggestion(asset_id="RTM-H-0007", fault_code="L-03",
                            summary="Repeat L-03 low suction: leak test and recharge",
                            citations=[NK600_SOP020_PASSAGE])
    return env.wo.create(env.who("u05"), None, s)


# --- US1 (user story: draft from an answer) ---------------------------------------------------

def test_us1_1_draft_from_the_restricted_suggestion(env):
    d = e31_draft(env)
    assert (d.asset_id, d.fault_code, d.target_system, d.status) == (
        "TAC-C-0143", "E-31", "maintpro", "draft")
    assert d.required_certification == ["cert-hv"]
    assert d.citations == [E31_PASSAGE]
    assert d.answer_id == "ans_example_q06" and d.created_by == "u03"
    assert d.approval_reasons == ["certification"] and d.eligible_approvers == ["u08"]
    assert d.idempotency_key and d.external_ref is None
    [ev] = env.events(draft_id=d.draft_id)
    assert (ev["kind"], ev["user_id"], ev["passage_ids"]) == ("draft_created", "u03", [E31_PASSAGE])
    assert ev["details"]["prefill"]["fault_code"] == "E-31"


def test_us1_2_edit_is_saved_and_audited_with_before_and_after(env):
    d = e31_draft(env)
    e = env.wo.edit(env.who("u03"), d.draft_id, {"summary": "E-31 trip twice since Monday"})
    assert e.summary == "E-31 trip twice since Monday"
    assert env.wo.get(env.who("u03"), d.draft_id).summary == "E-31 trip twice since Monday"
    ev = env.events(draft_id=d.draft_id, kind="draft_edited")[-1]
    assert ev["details"]["before"] == {"summary": d.summary}
    assert ev["details"]["after"] == {"summary": "E-31 trip twice since Monday"}


def test_edits_at_creation_are_audited_against_the_prefill(env):
    d = e31_draft(env, priority="high", summary="Drive trips on start")
    assert (d.priority, d.summary) == ("high", "Drive trips on start")
    [ev] = env.events(draft_id=d.draft_id)
    assert ev["details"]["edits"]["priority"] == {"before": "medium", "after": "high"}


def test_only_editable_fields_and_only_by_the_creator(env):
    d = e31_draft(env)
    with pytest.raises(InvalidRequest, match="required_certification"):
        env.wo.edit(env.who("u03"), d.draft_id, {"required_certification": []})
    with pytest.raises(InvalidRequest):
        env.wo.edit(env.who("u03"), d.draft_id, {"priority": "urgent"})
    with pytest.raises(InvalidRequest):
        env.wo.edit(env.who("u03"), d.draft_id, {"summary": "   "})
    with pytest.raises(Forbidden):
        env.wo.edit(env.who("u08"), d.draft_id, {"summary": "lead rewrites it"})
    assert env.wo.get(env.who("u03"), d.draft_id).summary == d.summary


# --- US2 (user story: approval when needed) ---------------------------------------------------

def test_us2_1_submit_is_refused_until_approved(env):
    d = e31_draft(env)
    with pytest.raises(InvalidState, match="certification"):
        env.wo.submit(env.who("u03"), d.draft_id, confirm=True, idempotency_key=d.idempotency_key)
    p = env.wo.request_approval(env.who("u03"), d.draft_id)
    assert p.status == "pending_approval"
    assert env.outbox_files() == []


def test_us2_2_na_lead_approves(env):
    a = approved_e31(env)
    assert (a.status, a.decided_by, a.decision_note) == (
        "approved", "u08", "ok, Kenji takes it Thursday")
    assert a.decided_at is not None
    assert env.events(draft_id=a.draft_id, kind="draft_approved")[0]["user_id"] == "u08"


def test_us2_3_eu_lead_cannot_approve_an_na_draft(env):
    d = e31_draft(env)
    env.wo.request_approval(env.who("u03"), d.draft_id)
    with pytest.raises(NotVisible):
        env.wo.approve(env.who("u07"), d.draft_id, None)
    assert env.wo.get(env.who("u03"), d.draft_id).status == "pending_approval"
    [denied] = env.events(draft_id=d.draft_id, kind="access_denied")
    assert (denied["user_id"], denied["outcome"]) == ("u07", "not_visible")
    assert denied["passage_ids"] == []


def test_us2_4_creator_cannot_approve_own_draft(env):
    env.set_groups("u13", ["region-na", "family-compressors", "cert-hv", "role-lead"])
    d = env.wo.create(env.who("u08"), None, restricted_suggestion())
    assert d.eligible_approvers == ["u13"]
    env.wo.request_approval(env.who("u08"), d.draft_id)
    with pytest.raises(Forbidden, match="own draft"):
        env.wo.approve(env.who("u08"), d.draft_id, None)
    with pytest.raises(Forbidden):
        env.wo.reject(env.who("u08"), d.draft_id, None)
    assert env.wo.approve(env.who("u13"), d.draft_id, None).decided_by == "u13"


def test_lead_alone_in_region_has_no_eligible_approver_for_own_draft(env):
    d = env.wo.create(env.who("u08"), None, restricted_suggestion())
    assert d.eligible_approvers == [] and "no eligible approver" in d.approval_reasons
    with pytest.raises(InvalidState, match="no eligible approver"):
        env.wo.request_approval(env.who("u08"), d.draft_id)


def test_a_non_lead_cannot_approve_even_if_they_can_see_the_draft(env):
    d = e31_draft(env)
    env.wo.request_approval(env.who("u03"), d.draft_id)
    with pytest.raises(NotVisible):  # u02 (NA technician with cert-hv) is neither creator nor lead
        env.wo.approve(env.who("u02"), d.draft_id, None)


def test_rejected_draft_keeps_the_note_and_can_go_back_for_approval(env):
    d = e31_draft(env)
    env.wo.request_approval(env.who("u03"), d.draft_id)
    r = env.wo.reject(env.who("u08"), d.draft_id, "add the fault history")
    assert (r.status, r.decision_note, r.decided_by) == ("rejected", "add the fault history", "u08")
    with pytest.raises(InvalidState):
        env.wo.submit(env.who("u03"), d.draft_id, confirm=True, idempotency_key=d.idempotency_key)
    e = env.wo.edit(env.who("u03"), d.draft_id, {"work_steps": "Tripped 3x since 10/10"})
    assert (e.status, e.decision_note) == ("draft", "add the fault history")
    assert env.wo.request_approval(env.who("u03"), d.draft_id).status == "pending_approval"
    assert env.wo.approve(env.who("u08"), d.draft_id, None).status == "approved"


def test_approve_needs_pending_state(env):
    d = e31_draft(env)
    with pytest.raises(InvalidState):
        env.wo.approve(env.who("u08"), d.draft_id, None)


# --- US3 (user story: submit exactly once) ----------------------------------------------------

def test_us3_1_approved_na_draft_goes_to_maintpro_once(env):
    a = approved_e31(env)
    s = env.wo.submit(env.who("u03"), a.draft_id, confirm=True, idempotency_key=a.idempotency_key)
    assert s.status == "submitted" and s.external_ref.startswith("MP-")
    assert env.outbox_files() == [f"maintpro/{a.idempotency_key}.json"]
    record = json.loads((env.outbox / "maintpro" / f"{a.idempotency_key}.json").read_text())
    assert record["external_ref"] == s.external_ref
    assert record["work_order"]["Asset"] == "TAC-C-0143" and record["work_order"]["Fault"] == "E-31"
    assert record["copilot"]["approved_by"] == "u08"


def test_us3_2_same_key_gives_same_result_and_one_file(env):
    a = approved_e31(env)
    key = a.idempotency_key
    first = env.wo.submit(env.who("u03"), a.draft_id, confirm=True, idempotency_key=key)
    path = env.outbox / "maintpro" / f"{key}.json"
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    again = env.wo.submit(env.who("u03"), a.draft_id, confirm=True, idempotency_key=key)
    assert again.external_ref == first.external_ref and again.status == "submitted"
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert env.outbox_files() == [f"maintpro/{key}.json"]
    outcomes = [e["outcome"] for e in env.events(draft_id=a.draft_id, kind="draft_submitted")]
    assert outcomes == ["submitted", "duplicate"]


def test_concurrent_submits_write_one_file(env):
    a = approved_e31(env)
    refs, errors = [], []

    def go():
        try:
            refs.append(env.wo.submit(env.who("u03"), a.draft_id, confirm=True,
                                      idempotency_key=a.idempotency_key).external_ref)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len(set(refs)) == 1 and len(refs) == 8
    assert env.outbox_files() == [f"maintpro/{a.idempotency_key}.json"]


def test_us3_3_rotterdam_chiller_goes_to_servio(env):
    s = WorkOrderSuggestion(asset_id="RTM-H-0007", fault_code="L-03",
                            summary="Check suction pressure after the L-03 alarm")
    d = env.wo.create(env.who("u05"), None, s)
    assert d.target_system == "servio" and d.approval_reasons == []
    done = env.wo.submit(env.who("u05"), d.draft_id, confirm=True,
                         idempotency_key=d.idempotency_key)
    assert done.external_ref.startswith("SV-")
    assert env.outbox_files() == [f"servio/{d.idempotency_key}.json"]
    record = json.loads((env.outbox / "servio" / f"{d.idempotency_key}.json").read_text())
    assert record["work_order"]["object"] == "RTM-H-0007"
    assert record["work_order"]["storingscode"] == "L-03"


def test_no_submit_without_confirm(env):
    a = approved_e31(env)
    for confirm in (False, None, "yes", 1):
        with pytest.raises(InvalidRequest, match="confirm"):
            env.wo.submit(env.who("u03"), a.draft_id, confirm=confirm,
                          idempotency_key=a.idempotency_key)
    assert env.wo.get(env.who("u03"), a.draft_id).status == "approved"
    assert env.outbox_files() == []
    refused = env.events(draft_id=a.draft_id, kind="draft_submitted")
    assert [e["outcome"] for e in refused] == ["invalid_request"] * 4


def test_submit_needs_this_drafts_key(env):
    a = approved_e31(env)
    for key in ("", "../../etc/passwd", "wo-someone-elses-key"):
        with pytest.raises(InvalidRequest):
            env.wo.submit(env.who("u03"), a.draft_id, confirm=True, idempotency_key=key)
    assert env.outbox_files() == []


def test_only_the_creator_submits(env):
    a = approved_e31(env)
    with pytest.raises(Forbidden):
        env.wo.submit(env.who("u08"), a.draft_id, confirm=True, idempotency_key=a.idempotency_key)


def test_outbox_failure_leaves_draft_approved_and_retry_is_safe(env):
    a = approved_e31(env)
    env.outbox.write_text("not a folder")
    with pytest.raises(SubmissionFailed) as e:
        env.wo.submit(env.who("u03"), a.draft_id, confirm=True, idempotency_key=a.idempotency_key)
    assert (e.value.code, e.value.http_status) == ("submission_failed", 503)
    assert env.wo.get(env.who("u03"), a.draft_id).status == "approved"
    env.outbox.unlink()
    s = env.wo.submit(env.who("u03"), a.draft_id, confirm=True, idempotency_key=a.idempotency_key)
    assert s.status == "submitted"
    assert env.outbox_files() == [f"maintpro/{a.idempotency_key}.json"]
    outcomes = [e["outcome"] for e in env.events(draft_id=a.draft_id, kind="draft_submitted")]
    assert outcomes == ["submission_failed", "submitted"]


def test_submitted_draft_is_not_editable(env):
    a = approved_e31(env)
    env.wo.submit(env.who("u03"), a.draft_id, confirm=True, idempotency_key=a.idempotency_key)
    with pytest.raises(NotEditable):
        env.wo.edit(env.who("u03"), a.draft_id, {"summary": "late change"})


# --- US4 (user story: drafts respect access) --------------------------------------------------

def test_us4_1_sop020_draft_hidden_from_someone_not_creator_or_approver(env):
    d = sop020_draft(env)
    with pytest.raises(NotVisible):
        env.wo.get(env.who("u11"), d.draft_id)
    assert d.draft_id not in [x.draft_id for x in env.wo.list_visible(env.who("u11"))]


def test_us4_2_eu_lead_without_refrigerant_cert_cannot_see_it_and_no_approver(env):
    d = sop020_draft(env)
    assert d.required_certification == ["cert-refrigerant"]
    with pytest.raises(NotVisible):
        env.wo.get(env.who("u07"), d.draft_id)
    assert d.draft_id not in [x.draft_id for x in env.wo.list_visible(env.who("u07"))]
    seen = env.wo.get(env.who("u05"), d.draft_id)
    assert "no eligible approver" in seen.approval_reasons and seen.eligible_approvers == []
    with pytest.raises(InvalidState, match="no eligible approver"):
        env.wo.request_approval(env.who("u05"), d.draft_id)
    with pytest.raises(InvalidState):
        env.wo.submit(env.who("u05"), d.draft_id, confirm=True, idempotency_key=d.idempotency_key)
    assert env.outbox_files() == []


def test_us4_3_access_is_rechecked_when_a_cited_passage_changes(env):
    d = sop020_draft(env)
    env.db.execute(f"UPDATE {env.schema}.drafts SET citations = citations || %s::text[]"
                   " WHERE draft_id = %s", [["p_gone_in_the_new_dataset"], d.draft_id])
    with pytest.raises(NotVisible):
        env.wo.get(env.who("u05"), d.draft_id)


def test_access_is_rechecked_when_the_creators_groups_change(env):
    d = sop020_draft(env)
    env.set_groups("u05", ["region-eu", "family-chillers"])
    with pytest.raises(NotVisible):
        env.wo.get(env.who("u05"), d.draft_id)
    with pytest.raises(NotVisible):
        env.wo.edit(env.who("u05"), d.draft_id, {"summary": "x"})
    assert env.wo.list_visible(env.who("u05"), mine=True) == []


def test_cannot_create_a_draft_citing_a_passage_you_cannot_see(env):
    s = WorkOrderSuggestion(asset_id="TAC-C-0143", summary="x", citations=[NK600_SOP020_PASSAGE])
    with pytest.raises(NotVisible):
        env.wo.create(env.who("u03"), None, s)
    assert env.db.execute(f"SELECT count(*) FROM {env.schema}.drafts").fetchone()[0] == 0
    [ev] = env.events(kind="access_denied")
    assert ev["user_id"] == "u03" and ev["details"]["action"] == "create"


def test_eligible_approvers_follow_users_json_on_the_next_read(env):
    d = e31_draft(env)
    assert d.eligible_approvers == ["u08"]
    env.set_groups("u08", ["region-na", "family-pumps", "cert-hv"])
    again = env.wo.get(env.who("u03"), d.draft_id)
    assert again.eligible_approvers == [] and "no eligible approver" in again.approval_reasons


def test_list_visible_shows_creator_and_region_leads_only(env):
    na = e31_draft(env)
    eu = WorkOrderSuggestion(asset_id="RTM-C-0120", summary="Oil level check")
    eu_draft = env.wo.create(env.who("u10"), None, eu)
    ids = lambda u, **kw: {x.draft_id for x in env.wo.list_visible(env.who(u), **kw)}  # noqa: E731
    assert ids("u03") == {na.draft_id}
    assert ids("u08") == {na.draft_id}
    assert ids("u08", mine=True) == set()
    assert ids("u07") == {eu_draft.draft_id}
    assert ids("u02") == set()


def test_not_found_vs_not_visible(env):
    with pytest.raises(NotFound):
        env.wo.get(env.who("u03"), "wo_does_not_exist")


# --- Edge cases -------------------------------------------------------------------------------

def test_hand_written_draft_without_citations_still_follows_approval_rules(env):
    s = WorkOrderSuggestion(asset_id="FRS-P-0031", summary="Replace seal kit",
                            parts=[{"part_number": "41-0046", "quantity": 2}])
    d = env.wo.create(env.who("u01"), None, s)
    assert d.citations == [] and d.approval_reasons == ["parts"]
    with pytest.raises(InvalidState):
        env.wo.submit(env.who("u01"), d.draft_id, confirm=True, idempotency_key=d.idempotency_key)


def test_adding_parts_by_edit_makes_approval_needed(env):
    d = env.wo.create(env.who("u01"), None,
                      WorkOrderSuggestion(asset_id="FRS-P-0031", summary="Strainer"))
    assert d.approval_reasons == []
    e = env.wo.edit(env.who("u01"), d.draft_id, {"parts": [{"part_number": "41-0046"}]})
    assert e.approval_reasons == ["parts"] and e.parts[0].quantity == 1


@pytest.mark.parametrize("field, reason", [("needs_specialist", "specialist"),
                                           ("return_visit", "return visit")])
def test_specialist_and_return_visit_need_approval(env, field, reason):
    d = env.wo.create(env.who("u01"), None,
                      WorkOrderSuggestion(asset_id="FRS-P-0031", summary="Seal leak"))
    assert (getattr(d, field), d.approval_reasons) == (False, [])
    e = env.wo.edit(env.who("u01"), d.draft_id, {field: True})
    assert getattr(e, field) is True and e.approval_reasons == [reason]
    assert e.eligible_approvers == ["u08"]
    with pytest.raises(InvalidState, match=reason):
        env.wo.submit(env.who("u01"), d.draft_id, confirm=True, idempotency_key=d.idempotency_key)
    ev = env.events(draft_id=d.draft_id, kind="draft_edited")[-1]
    assert ev["details"]["before"] == {field: False} and ev["details"]["after"] == {field: True}
    with pytest.raises(InvalidRequest):
        env.wo.edit(env.who("u01"), d.draft_id, {field: "yes"})
    assert env.wo.edit(env.who("u01"), d.draft_id, {field: False}).approval_reasons == []


def test_flags_reach_the_outbox_record(env):
    d = env.wo.create(env.who("u01"), None,
                      WorkOrderSuggestion(asset_id="FRS-P-0031", summary="Seal leak"))
    env.wo.edit(env.who("u01"), d.draft_id, {"return_visit": True})
    env.wo.request_approval(env.who("u01"), d.draft_id)
    env.wo.approve(env.who("u08"), d.draft_id, None)
    env.wo.submit(env.who("u01"), d.draft_id, confirm=True, idempotency_key=d.idempotency_key)
    record = json.loads((env.outbox / "maintpro" / f"{d.idempotency_key}.json").read_text())
    assert (record["copilot"]["return_visit"], record["copilot"]["needs_specialist"]) == (
        True, False)


def test_citations_are_not_editable(env):
    d = sop020_draft(env)
    with pytest.raises(InvalidRequest, match="citations"):
        env.wo.edit(env.who("u05"), d.draft_id, {"citations": []})
    again = env.wo.get(env.who("u05"), d.draft_id)
    assert again.citations == [NK600_SOP020_PASSAGE]
    assert again.required_certification == ["cert-refrigerant"]


def test_required_certification_keeps_cert_groups_only(env):
    s = WorkOrderSuggestion(asset_id="RTM-H-0007", summary="Leak test and recharge",
                            required_certification=["family-chillers", "cert-refrigerant",
                                                    "region-eu"],
                            citations=[NK600_SOP020_PASSAGE])
    d = env.wo.create(env.who("u05"), None, s)
    assert d.required_certification == ["cert-refrigerant"]
    [ev] = env.events(draft_id=d.draft_id)
    assert ev["details"]["non_certification_groups_dropped"] == ["family-chillers", "region-eu"]
    assert ev["details"]["certification_added_by_rule"] == []


def test_unknown_region_is_refused_at_creation(env, monkeypatch):
    real = env.wo._s.asset
    monkeypatch.setattr(env.wo._s, "asset", lambda conn, a: {**real(conn, a), "region": None})
    with pytest.raises(InvalidRequest, match="no known region") as e:
        env.wo.create(env.who("u03"), None, restricted_suggestion())
    assert e.value.http_status == 422
    assert env.db.execute(f"SELECT count(*) FROM {env.schema}.drafts").fetchone()[0] == 0


def test_asset_is_required_and_must_exist(env):
    no_asset = WorkOrderSuggestion(summary="BX-12 belt tracks left",
                                   parts=[{"part_number": "77-0419"}])
    with pytest.raises(InvalidRequest, match="asset_id"):
        env.wo.create(env.who("u12"), None, no_asset)
    with pytest.raises(InvalidRequest, match="unknown asset"):
        env.wo.create(env.who("u12"), None, no_asset, asset_id="XXX-0000")
    picked = env.wo.create(env.who("u12"), None, no_asset, asset_id="FRS-V-0201")
    assert picked.asset_id == "FRS-V-0201" and picked.target_system == "maintpro"
    with pytest.raises(InvalidRequest):
        env.wo.create(env.who("u03"), None, restricted_suggestion(), asset_id="TAC-C-0142")


# --- Audit log --------------------------------------------------------------------------------

def test_full_flow_audits_every_action(env):
    a = approved_e31(env)
    env.wo.submit(env.who("u03"), a.draft_id, confirm=True, idempotency_key=a.idempotency_key)
    kinds = [(e["kind"], e["outcome"]) for e in env.events(draft_id=a.draft_id)]
    assert kinds == [("draft_created", "created"), ("draft_edited", "approval_requested"),
                     ("draft_approved", "approved"), ("draft_submitted", "submitted")]
    for e in env.events(draft_id=a.draft_id):
        assert e["passage_ids"] == [E31_PASSAGE]


def test_audit_table_is_append_only(env):
    import psycopg

    e31_draft(env)
    for stmt in (f"UPDATE {env.schema}.audit_events SET outcome = 'x'",
                 f"DELETE FROM {env.schema}.audit_events",
                 f"TRUNCATE {env.schema}.audit_events"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            env.db.execute(stmt)
    assert env.db.execute(f"SELECT count(*) FROM {env.schema}.audit_events").fetchone()[0] == 1


def test_record_ignores_a_duplicate_event_id(env):
    from datetime import UTC, datetime

    from copilot_contracts.work_orders import AuditEvent

    ev = AuditEvent(event_id="ev_answer_1", at=datetime.now(UTC), user_id="u03", kind="answer",
                    answer_id="ans_1", dataset_version="ds_0028", passage_ids=[E31_PASSAGE],
                    outcome="restricted")
    env.audit.record(ev)
    env.audit.record(ev.model_copy(update={"outcome": "changed"}))
    [stored] = env.audit.visible_events(env.who("u03"), answer_id="ans_1")
    assert stored == ev


def test_visible_events_follow_the_draft_rule(env):
    from datetime import UTC, datetime

    from copilot_contracts.work_orders import AuditEvent

    d = sop020_draft(env)
    env.audit.record(AuditEvent(event_id="ev_a", at=datetime.now(UTC), user_id="u03",
                                kind="answer", answer_id="ans_q06", passage_ids=[E31_PASSAGE],
                                outcome="restricted"))
    assert [e.kind for e in env.audit.visible_events(env.who("u05"), draft_id=d.draft_id)] == [
        "draft_created"]
    assert env.audit.visible_events(env.who("u11"), draft_id=d.draft_id) == []
    assert env.audit.visible_events(env.who("u07"), draft_id=d.draft_id) == []
    assert len(env.audit.visible_events(env.who("u03"), answer_id="ans_q06")) == 1
    assert env.audit.visible_events(env.who("u08"), answer_id="ans_q06") == []
    mine = env.audit.visible_events(env.who("u05"))
    assert [e.draft_id for e in mine] == [d.draft_id]
