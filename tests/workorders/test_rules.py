import inspect
from datetime import UTC, datetime

from copilot_contracts import services
from copilot_workorders import PgAuditLog, PgWorkOrders, rules


def test_approval_needs_lists_each_reason():
    assert rules.approval_needs([], [], None) == []
    assert rules.approval_needs([{"part_number": "63-1180", "quantity": 2}], ["cert-refrigerant"],
                                "NK-C25-14") == ["parts", "certification", "campaign"]
    assert rules.approval_needs([], [], None, needs_specialist=True, return_visit=True) == [
        "specialist", "return visit"]


def test_certifications_keep_cert_groups_only():
    assert rules.certifications(["cert-refrigerant", "family-chillers", "region-eu",
                                 "cert-hv"]) == ["cert-refrigerant", "cert-hv"]


def test_submission_failed_is_the_shared_contract_class():
    import copilot_workorders

    assert copilot_workorders.SubmissionFailed is services.SubmissionFailed
    assert "needs_specialist" in rules.EDITABLE and "return_visit" in rules.EDITABLE
    assert "citations" not in rules.EDITABLE


def test_target_system_follows_region():
    assert rules.target_system("NA") == "maintpro"
    assert rules.target_system("EU") == "servio"
    assert rules.target_system(None) is None
    assert rules.target_system("APAC") is None


def test_lead_needs_role_and_region():
    assert rules.is_lead_for({"role-lead", "region-na"}, "NA")
    assert not rules.is_lead_for({"role-lead", "region-eu"}, "NA")
    assert not rules.is_lead_for({"region-na", "cert-hv"}, "NA")


def test_keys_are_safe_file_names():
    assert rules.valid_key("wo-0123abcd")
    for bad in ["", None, "../x", "a/b", ".hidden", "x" * 129, "a b"]:
        assert not rules.valid_key(bad)


def test_external_ref_is_stable_per_key_and_system():
    assert rules.external_ref("maintpro", "k1") == rules.external_ref("maintpro", "k1")
    assert rules.external_ref("maintpro", "k1").startswith("MP-")
    assert rules.external_ref("servio", "k1").startswith("SV-")
    assert rules.external_ref("maintpro", "k1") != rules.external_ref("maintpro", "k2")


def test_procedure_groups_are_those_every_alternative_needs():
    alts = [frozenset({"cert-hv", "family-compressors"}), frozenset({"cert-hv", "role-lead"})]
    assert rules.required_groups_of(alts) == {"cert-hv"}
    assert rules.required_groups_of([]) == set()


def _draft(**kw):
    base = {"draft_id": "wo_1", "answer_id": None, "created_by": "u03", "summary": "E-31 trip",
            "work_steps": "", "fault_code": "E-31", "priority": "high",
            "parts": [{"part_number": "41-0046", "quantity": 2}, {"part_number": "41-1470",
                                                                  "quantity": 1}],
            "required_certification": ["cert-hv"], "campaign_code": None, "citations": [],
            "decided_by": "u08"}
    return {**base, **kw}


ASSET = {"asset_id": "TAC-C-0143", "model": "VRS-110", "serial": "VRS110-240210", "site": "TAC",
         "site_name": "Tacoma Cold Storage", "region": "NA"}
AT = datetime(2026, 10, 12, 21, 0, tzinfo=UTC)


def test_maintpro_record_uses_maintpro_export_fields():
    rec = rules.outbox_record(system="maintpro", key="k", ref="MP-1", draft=_draft(), asset=ASSET,
                              submitted_by="u03", submitted_at=AT)
    wo = rec["work_order"]
    assert wo["WO_No"] == "MP-1" and wo["Date"] == "10/12/2026" and wo["Asset"] == "TAC-C-0143"
    assert wo["Parts"] == "41-0046 x2; 41-1470 x1" and wo["Event_Type"] == "CM"
    assert rec["copilot"]["approved_by"] == "u08"


def test_servio_record_uses_servio_export_fields():
    rec = rules.outbox_record(system="servio", key="k", ref="SV-1", draft=_draft(),
                              asset={**ASSET, "site_name": "Rotterdam DC Maasvlakte"},
                              submitted_by="u05", submitted_at=AT)
    wo = rec["work_order"]
    assert wo["datum"] == "12-10-2026" and wo["type"] == "Storing"
    assert wo["onderdelen"] == "2x 41-0046, 1x 41-1470"
    assert wo["locatie"] == "Rotterdam DC Maasvlakte"


def _public(cls):
    return {n: inspect.signature(f) for n, f in vars(cls).items()
            if callable(f) and not n.startswith("_")}


def test_implementations_match_the_service_protocols_exactly():
    for impl, proto in [(PgWorkOrders, services.WorkOrders), (PgAuditLog, services.AuditLog)]:
        mine, theirs = _public(impl), _public(proto)
        assert set(theirs) <= set(mine)
        for name, sig in theirs.items():
            assert list(mine[name].parameters) == list(sig.parameters), name
            for p, q in zip(mine[name].parameters.values(), sig.parameters.values(), strict=True):
                assert (p.kind, p.default) == (q.kind, q.default), f"{name}.{p.name}"
