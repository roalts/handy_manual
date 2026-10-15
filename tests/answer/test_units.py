"""Deterministic pieces of the engine: validator, identifiers, resolution, applicability,
restricted detection."""
from copilot_answer.applicability import Candidate, apply
from copilot_answer.ids import recognize
from copilot_answer.resolve import Fleet, candidates_differ, resolve
from copilot_answer.restricted import (
    covering,
    guard,
    marker_hits,
    names_in,
    scope_terms,
    terms,
    unsatisfied,
)
from copilot_answer.serving import Asset, Document, Passage, ProcedureAlt, Relation
from copilot_answer.validate import MONTH_DAY, check_sentence, dates, norm, strip_labels, tags

# ------------------------------------------------------------------ validator

TABLE_500 = "Fault P-07 cavitation: clean strainer when differential exceeds 0.30 bar."
TABLE_350 = "Torque (N-m)\nCasing bolts 45\nImpeller nut 60"


def test_value_must_be_in_cited_passage():
    supplied = {"P1": TABLE_500, "P2": "Strainer limit 0.25 bar on HCP-350."}
    assert check_sentence("Clean it above 0.30 bar.", ["P1"], supplied).ok
    bad = check_sentence("Clean it above 0.25 bar.", ["P1"], supplied)
    assert not bad.ok and "0.25 bar" in bad.reason


def test_uncited_supplied_passage_does_not_ground():
    supplied = {"P1": TABLE_500, "P2": "See case 00041988."}
    assert not check_sentence("As in case 00041988.", ["P1"], supplied).ok
    assert check_sentence("As in case 00041988.", ["P2"], supplied).ok


def test_citation_to_unsupplied_passage_fails():
    assert not check_sentence("Clean the strainer.", ["P9"], {"P1": TABLE_500}).ok


def test_unit_from_table_header_and_spelling_variants():
    supplied = {"P1": TABLE_350}
    assert check_sentence("Torque the casing bolts to 45 N·m.", ["P1"], supplied).ok
    assert check_sentence("Torque the casing bolts to 45 Nm.", ["P1"], supplied).ok
    assert not check_sentence("Torque the casing bolts to 50 N-m.", ["P1"], supplied).ok


def test_number_formats_normalise():
    assert norm("1.000 V DC") != norm("1 V DC")
    supplied = {"P1": "Megger at 1,000 V DC, limit 0,38–0,50 mm."}
    assert check_sentence("Test at 1000 V DC.", ["P1"], supplied).ok
    assert check_sentence("Clearance 0.38-0.50 mm.", ["P1"], supplied).ok


def test_identifiers_are_checked():
    supplied = {"P1": "Replace TS-2 (41-2207). Fault E-14."}
    assert check_sentence("Replace part 41-2207 for E-14.", ["P1"], supplied).ok
    assert not check_sentence("Replace part 41-2208.", ["P1"], supplied).ok
    assert not check_sentence("This is fault E-15.", ["P1"], supplied).ok


def test_asset_record_grounds_the_machine_identity():
    supplied = {"P1": "Check TS-2 against a handheld probe."}
    record = "TAC-C-0142 VRS-110 serial VRS110-220190 firmware 5.0"
    assert check_sentence("On TAC-C-0142, check TS-2.", ["P1"], supplied, record).ok
    assert not check_sentence("On TAC-C-0142, check TS-2.", ["P1"], supplied).ok


def test_unverified_marker_must_be_copied_from_cited_passage():
    supplied = {"P1": "Clearance [[unverified:v_12|page=4]] mm."}
    assert check_sentence("Clearance is [[unverified:v_12|page=4]] mm.", ["P1"], supplied).ok
    assert not check_sentence("Clearance is [[unverified:v_99|page=4]] mm.", ["P1"],
                              supplied).ok


# ------------------------------------------------------------------ identifiers

def test_recognize_spacing_tolerant_ids():
    r = recognize("tac c 0143 tripped on E31, case 00041207, part 41-2207, HCP 350")
    assert r.asset_ids == ["TAC-C-0143"]
    assert r.fault_codes == ["E-31"]
    assert r.case_numbers == ["00041207"]
    assert r.part_numbers == ["41-2207"]
    assert r.models == ["HCP-350"]


def test_campaign_code_is_not_a_fault_code():
    r = recognize("Campaign NK-C25-14 for L-03")
    assert r.fault_codes == ["L-03"]


# ------------------------------------------------------------------ resolution

FLEET = Fleet(
    {a.asset_id: a for a in [
        Asset("FRS-P-0012", "HCP-350", "HCP350-230100", "FRS", "Fresno Bottling Plant", "NA"),
        Asset("FRS-P-0031", "HCP-350", "HCP350-241187", "FRS", "Fresno Bottling Plant", "NA"),
        Asset("TAC-C-0143", "VRS-110", "VRS110-220311", "TAC", "Tacoma Plant", "NA", "5.0"),
    ]},
    {"FP-31": "FRS-P-0031"}, {})


def _resolve(q, asset_id=None):
    return resolve(q, recognize(q), FLEET, asset_id)


def test_resolve_by_asset_id_serial_and_legacy_alias():
    assert _resolve("seal on FRS-P-0031?").asset.asset_id == "FRS-P-0031"
    assert _resolve("seal on HCP350-241187?").asset.asset_id == "FRS-P-0031"
    assert _resolve("anything", asset_id="FRS-P-0012").asset.asset_id == "FRS-P-0012"


def test_unknown_id_is_reported_not_guessed():
    r = _resolve("seal on FRS-P-9999?")
    assert r.asset is None and r.unknown == "FRS-P-9999"


def test_model_and_site_gives_candidates():
    r = _resolve("casing torque on the HCP-350 at Fresno?")
    assert r.asset is None
    assert {a.asset_id for a in r.candidates} == {"FRS-P-0012", "FRS-P-0031"}
    assert candidates_differ(r.candidates, {"FRS-P-0012": {"sb": "not_affected"},
                                            "FRS-P-0031": {"sb": "affected"}})
    assert not candidates_differ(r.candidates, {"FRS-P-0012": {"sb": "affected"},
                                                "FRS-P-0031": {"sb": "affected"}})


def test_model_only_question():
    r = _resolve("casing torque on an HCP-350?")
    assert r.asset is None and r.models == ["HCP-350"] and r.candidates == []


# ------------------------------------------------------------------ applicability

def _cand(pid, doc, **kw):
    return Candidate(Passage(pid, doc.doc_id, "text", **kw), doc)


def test_applicability_filters_model_superseded_and_stale():
    man_b = Document("d_b", "VRS-75 Manual Rev B", "service_manual", 3, ("VRS-75",), "B")
    man_c = Document("d_c", "VRS-75 Manual Rev C", "service_manual", 3, ("VRS-75",), "C")
    wiki = Document("d_w", "Quick reference", "wiki", 4, ("VRS-75",))
    other = Document("d_o", "VRS-110 Manual", "service_manual", 3, ("VRS-110",))
    general = Document("d_g", "Field standard", "controlled_procedure", 1)
    rels = [Relation("d_c", "d_b", "supersedes"), Relation("d_w", "d_c", "possibly_stale_vs")]
    cands = [_cand("b", man_b), _cand("c", man_c), _cand("w", wiki), _cand("o", other),
             _cand("g", general)]
    out = apply(cands, ["VRS-75"], None, rels, {"d_b", "d_c", "d_w", "d_o", "d_g"}, {})
    assert [c.pid for c in out.evidence] == ["c", "g"]
    assert [c.pid for c in out.superseded] == ["b"]
    assert [c.pid for c in out.stale] == ["w"]
    assert [c.pid for c in out.dropped_model] == ["o"]


def test_superseded_kept_and_labelled_when_newer_is_not_visible():
    man_b = Document("d_b", "Rev B", "service_manual", 3, ("VRS-75",), "B")
    out = apply([_cand("b", man_b)], ["VRS-75"], None, [Relation("d_c", "d_b", "supersedes")],
                {"d_b"}, {})
    assert [c.pid for c in out.evidence] == ["b"]
    assert "SUPERSEDED revision" in out.evidence[0].labels


def test_records_labelled_by_unit_and_model_from_fleet():
    cases = Document("d_sf", "Salesforce cases", "case_export", 0)
    asset = FLEET.assets["FRS-P-0031"]
    mine = _cand("m", cases, asset_ids=["FRS-P-0031"])
    other = _cand("x", cases, asset_ids=["FRS-P-0012"])
    vrs = _cand("v", cases, asset_ids=["TAC-C-0143"])
    models = {a.asset_id: a.model for a in FLEET.assets.values()}
    out = apply([mine, other, vrs], ["HCP-350"], asset, [], {"d_sf"}, {}, models)
    assert [c.pid for c in out.evidence] == ["m", "x"]
    assert out.evidence[1].other_unit
    assert [c.pid for c in out.dropped_model] == ["v"]


def test_bulletin_status_comes_from_fleet_records():
    sb = Document("d_sb", "SB-2025-009", "bulletin", 2, ("HCP-350",))
    out = apply([_cand("s", sb)], ["HCP-350"], FLEET.assets["FRS-P-0012"], [], {"d_sb"},
                {"d_sb": "not_affected"})
    assert out.evidence[0].bulletin_status == "not_affected"


# ------------------------------------------------------------------ restricted

PROCS = [
    ProcedureAlt("HV-PROC-07", "VFD Fault Reset", "d7", frozenset({"cert-hv",
                                                                   "family-compressors"})),
    ProcedureAlt("SOP-020", "Leak test", "d20", frozenset({"cert-refrigerant",
                                                          "family-chillers"})),
    ProcedureAlt("SOP-020", "Leak test", "d20", frozenset({"cert-refrigerant", "role-lead"})),
]


def test_unsatisfied_uses_any_alternative_and_smallest_gap():
    u = unsatisfied(PROCS, frozenset({"family-compressors", "family-chillers"}))
    assert u["HV-PROC-07"].missing_groups == ("cert-hv",)
    assert u["SOP-020"].missing_groups == ("cert-refrigerant",)
    assert "SOP-020" not in unsatisfied(PROCS, frozenset({"cert-refrigerant", "role-lead"}))


def test_names_and_markers_detected_through_formatting():
    assert names_in("done under hv proc 07 only", ["HV-PROC-07", "SOP-020"]) == ["HV-PROC-07"]
    assert names_in("see HV-PROC-071", ["HV-PROC-07"]) == []
    markers = ("1,000 V DC", "P9.01", "TP1")
    assert marker_hits("megger at 1000 VDC then set p9.01", markers) == ["1,000 V DC", "P9.01"]
    assert marker_hits("check TP12 and P9.010", markers) == []
    assert guard("Set P9.01 to 1", ["HV-PROC-07"], {"HV-PROC-07": markers}) == ["P9.01"]
    assert guard("Set P9.01 to 1", [], {"HV-PROC-07": markers}) == []


# ------------------------------------------------------------------ conflicts

def test_conflict_precedence_applying_bulletin_then_authority_tier():
    from copilot_answer.build import preferred_side

    iom = _cand("i", Document("d_i", "IOM Rev D", "service_manual", 3, ("HCP-350",)))
    sb = _cand("s", Document("d_s", "SB-2025-009", "bulletin", 2, ("HCP-350",)))
    sb.bulletin_status = "affected"
    wi = _cand("w", Document("d_w", "KT-WI-14", "work_instruction", 1))
    sop = _cand("p", Document("d_p", "SOP-020", "controlled_procedure", 1))
    wiki = _cand("k", Document("d_k", "Playbook", "wiki", 4))
    case = _cand("c", Document("d_c", "Cases", "case_export", 0))
    assert preferred_side([[iom], [sb]])[0] == 1
    assert preferred_side([[wiki, case], [iom]])[0] == 1
    assert preferred_side([[wi], [sop]])[0] is None


# ------------------------------------------------------------------ evidence labels

def test_strip_labels_removes_bracketed_evidence_labels():
    assert strip_labels("Replace the return idler [P4].") == "Replace the return idler."
    assert strip_labels("Fit 77-0419 (P4, P7) on both sides.") == "Fit 77-0419 on both sides."
    assert strip_labels("Check tracking [P4][P7], then run.") == "Check tracking, then run."
    assert strip_labels("See [P2; P10] and [Passage 3].") == "See and."
    assert strip_labels("Lot 23-11 idlers (P4 and P7) have an off-centre bore.") == (
        "Lot 23-11 idlers have an off-centre bore.")


def test_strip_labels_keeps_identifiers_in_brackets():
    for text in ["Set P9.01 (P9.01 = 1) on the keypad.", "Measure at TP1 (TP1-TP2).",
                 "Fault (P-07) is cavitation.", "Clean the strainer (section 8.3).",
                 "Value [[unverified:v_1|page=3]] on page 3.", "Use parameter P4 for speed."]:
        assert strip_labels(text) == text


# ------------------------------------------------------------------ tags and dates

def test_tags_are_sensor_and_test_point_labels_only():
    text = ("Compare TS-2 with the probe, read PI-01/PI-02, measure TP1-TP2, check EXV-2 and X10; "
            "E-14 on TAC-C-0142 (VRS-110, HCP-500), set P9.01, per SOP-020 and HV-PROC-07, "
            "campaign NK-C25-14, part 63-1180, R-513A, case 00042388.")
    assert tags(text) == ["TS-2", "PI-01", "PI-02", "TP1", "TP2", "EXV-2", "X10"]


def test_sensor_tag_must_be_in_the_sentences_own_citations():
    supplied = {"P1": "Controller log: 3x E-14 auto restart since July.",
                "P2": "On firmware below 5.1 a failing TS-2 is reported as E-14."}
    text = "The likely cause is a failing TS-2 being reported as E-14."
    v = check_sentence(text, ["P1"], supplied)
    assert not v.ok and v.missing == ["TS-2"]
    assert check_sentence(text, ["P1", "P2"], supplied).ok


def test_tag_the_technician_typed_may_be_repeated():
    supplied = {"P1": "Entry into a permit space is done under CS-PROC-03."}
    text = "Entering pit PP-1 is work under CS-PROC-03."
    assert not check_sentence(text, ["P1"], supplied).ok
    assert check_sentence(text, ["P1"], supplied,
                          typed="How do I enter pump pit PP-1 safely?").ok


def test_dates_in_a_sentence():
    assert dates("On 2026-07-28, 28 July 2026 and August 30, 2026, see 2026-09-17.") == [
        (2026, 7, 28), (2026, 9, 17), (2026, 8, 30)]
    assert dates("Rev 2025-14 and serial HCP350-240001") == []


def test_date_matches_the_passages_own_format():
    record = {"P1": "Case 00044010 opened 2026-09-22. E-14 auto restart since July (07/28, 08/30)."}
    assert check_sentence("E-14 restarted on 2026-07-28 and 2026-08-30.", ["P1"], record).ok
    assert check_sentence("It was opened on 22 September 2026.", ["P1"], record).ok
    v = check_sentence("E-14 restarted on 2026-07-29.", ["P1"], record)
    assert not v.ok and v.missing == ["2026-07-29"]
    assert not check_sentence("E-14 restarted on 2025-07-28.", ["P1"], record).ok
    no_year = {"P1": "E-14 auto restarts on 07/28 and 08/30."}
    assert not check_sentence("E-14 restarted on 2026-07-28.", ["P1"], no_year).ok
    long = {"P1": "Wartung am 28.07.2026; next visit July 30, 2026."}
    assert check_sentence("Serviced on 2026-07-28, next on 2026-07-30.", ["P1"], long).ok


def test_a_date_without_its_year_must_be_in_the_cited_passages():
    cited = {"P1": "2026-07-02 E-14 trip, TS-2 replaced.", "P2": "Visit 01.07.2026, fins cleaned."}
    v = check_sentence("It tripped again on 2026-07-02 after the 07-01 cleanup.", ["P1"], cited)
    assert not v.ok and v.missing == ["07-01"]
    assert check_sentence("It tripped again after the 07-01 cleanup.", ["P2"], cited).ok
    assert check_sentence("Tripped on 07/02.", ["P1"], cited).ok
    assert MONTH_DAY.findall("10-12 bar, part 06-1180, 2026-07-02, 3-5 turns") == []


# ------------------------------------------------------------------ completeness candidates

CASE_TEXT = ("Case 00041988, FRS-P-0031. Opened 2026-06-03. The casing joint wept at 5.5 bar; the "
             "gasket seat was cracked. Fault table: E-30 drive communication, E-31 overcurrent. "
             "If the joint leaks at 38 N-m, stop, isolate and drain the pump before you open it.")


def test_missing_lists_what_the_cited_passages_hold_and_the_answer_does_not():
    from copilot_answer.complete import missing

    items = missing(["Use 38 N-m on FRS-P-0031."], {"P1": CASE_TEXT}, 40,
                    "Casing torque on FRS-P-0031?")
    got = {(i.kind, i.text) for i in items}
    assert ("identifier", "00041988") in got
    assert ("date", "2026-06-03") in got
    assert ("value", "5.5 bar") in got
    assert any(k == "branch" and t.startswith("If the joint leaks") for k, t in got)
    assert all(i.label == "P1" for i in items)
    assert items[0].kind == "branch"
    # Present in the answer, or a fault code the question doesn't name: not listed.
    assert not {"FRS-P-0031", "38 N-m", "E-30", "E-31"} & {t for _, t in got}


def test_missing_counts_a_branch_the_answer_already_states_and_keeps_asked_fault_codes():
    from copilot_answer.complete import missing

    answer = ["If the joint leaks at 38 N-m, stop, isolate and drain the pump before opening it."]
    items = missing(answer, {"P1": CASE_TEXT}, 40, "What does E-31 mean?")
    assert not [i for i in items if i.kind == "branch"]
    assert ("identifier", "E-31") in {(i.kind, i.text) for i in items}
    assert len(missing(answer, {"P1": CASE_TEXT}, 2, "")) == 2


# ------------------------------------------------------------------ restricted backstop

# The four procedures as published in serving.restricted_procedures (ds_0028).
PUBLISHED = [
    ProcedureAlt("CS-PROC-03", "CS-PROC-03 Confined Space Entry, Pump Pits", "d_cs3",
                 frozenset({"cert-confined-space"})),
    ProcedureAlt("HV-PROC-02", "HV-PROC-02 Electrical Isolation Verification", "d_hv2",
                 frozenset({"cert-hv"})),
    ProcedureAlt("HV-PROC-07", "HV-PROC-07 VRS-110 VFD Fault Reset", "d_hv7",
                 frozenset({"cert-hv", "family-compressors"})),
    ProcedureAlt("SOP-020", "SOP-020 Chiller Leak Test and Refrigerant Recharge", "d_sop20",
                 frozenset({"cert-refrigerant", "family-chillers"})),
]
U01 = frozenset({"region-na", "family-pumps"})
U03 = frozenset({"region-na", "family-compressors"})
PIT = "I need to clean the foot strainer in pump pit PP-1 at Fresno. How do I enter the pit safely?"
ISOLATE = ("How do I electrically isolate TAC-C-0142 and prove the VFD cabinet is dead before I "
           "work inside it?")


def _cover(question: str, groups: frozenset[str]):
    found = covering(question, unsatisfied(PUBLISHED, groups), 2)
    return found.name if found else None


def test_scope_terms_come_from_the_title_without_the_name():
    uns = unsatisfied(PUBLISHED, U01)
    assert scope_terms(uns["CS-PROC-03"]) == {"confi", "space", "entry", "pump", "pit"}
    assert scope_terms(uns["HV-PROC-07"]) == {"vrs-110", "vfd", "fault", "reset"}
    assert terms("electrically isolate") == terms("Electrical Isolation")


def test_backstop_covers_the_two_uncertified_pairs():
    assert _cover(PIT, U01) == "CS-PROC-03"  # pump, pit
    assert _cover(ISOLATE, U03) == "HV-PROC-02"  # electrical, isolation beat VFD alone


def test_backstop_leaves_certified_users_and_satisfied_procedures_alone():
    u08 = frozenset({"region-na", "family-pumps", "family-compressors", "cert-hv",
                     "cert-confined-space", "role-lead"})
    u02 = frozenset({"region-na", "family-compressors", "cert-hv"})
    assert _cover(PIT, u08) is None
    assert _cover(ISOLATE, u02) is None
    assert _cover("TAC-C-0143 tripped on E-31. How do I reset it?", u02) is None
    assert _cover("How do I recover and recharge the refrigerant on an NK-600?",
                  frozenset({"region-eu", "family-chillers", "cert-refrigerant"})) is None


def test_backstop_needs_a_how_to_question_about_the_work():
    assert _cover("What does CS-PROC-03 cover for the pump pits?", U01) is None
    assert _cover("Which certification do I need to enter pump pit PP-1?", U01) is None
    assert _cover("How do I clean the strainer on the pump?", U01) is None  # pump alone


def test_backstop_changes_no_golden_or_paired_answer():
    import json

    from copilot_ingest.settings import PROJECT_ROOT
    from tests.answer.test_golden import EXPECT, EXTRA

    groups = {u["id"]: frozenset(u["groups"])
              for u in json.loads((PROJECT_ROOT / "users.json").read_text())["users"]}
    cases = [(q["user_id"], q["question"], EXPECT[q["id"]][0])
             for q in json.loads((PROJECT_ROOT / "eval/questions.json").read_text())]
    cases += [(e[1], e[2], e[3]) for e in EXTRA]
    for user, question, outcome in cases:
        if outcome != "restricted":
            assert _cover(question, groups[user]) is None, question
