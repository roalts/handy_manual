"""Writes the example responses in this folder from ds_0026 (dataset version 26) passage IDs and
checks them against copilot_contracts. Run: uv run python specs/contracts/examples/build.py"""
import json
from pathlib import Path

from copilot_contracts import (
    AnswerResponse,
    AssetBulletin,
    Citation,
    Clarification,
    ClarifyOption,
    Conflict,
    ConflictSide,
    Notice,
    ResolvedAsset,
    Restricted,
    Segment,
    Sentence,
    WorkOrderSuggestion,
)

HERE = Path(__file__).parent
SB = "doc_1a07169971035ffd70cf5a81"
IOM_DOC = "doc_4d743829d1cbdd028b477127"
SF_NA = "doc_0bd1ab36c93e82068dca8079"
PLAYBOOK = "doc_14fc892297a50b91a4202670"
HCP200_DOC = "doc_6c7fca788eb5c49afe2201d6"


def text(s: str) -> list[Segment]:
    return [Segment(kind="text", text=s)]


def cite(pid: str, doc_id: str, title: str, doc_type: str, tier: int, locator: str,
         revision: str | None = None, **flags) -> Citation:
    return Citation(passage_id=pid, doc_id=doc_id, title=title, doc_type=doc_type,
                    revision=revision, issue_date=None, authority_tier=tier, locator=locator,
                    viewer_url=f"/sources/{pid}", **flags)


FRS_P_0031 = ResolvedAsset(
    asset_id="FRS-P-0031", model="HCP-350", serial="HCP350-241187", firmware="3.4", site="FRS",
    site_name="Fresno Bottling Plant", region="NA",
    bulletins=[AssetBulletin(doc_id=SB, title="Halden SB-2025-009",
                             status="affected", citations=["p_e35d98a44e996383173e0193"],
                             reason="HCP350-240001 and later: Version 2 cover, 38 N-m")])

SB_SUMMARY = cite("p_32f5ef652cfa89ebd0e95aaf", SB, "Halden SB-2025-009",
                  "bulletin", 2, "p. 1, 1 Summary")
SB_TABLE = cite("p_e35d98a44e996383173e0193", SB, "Halden SB-2025-009",
                "bulletin", 2, "p. 1, 2 Affected products")
IOM = cite("p_79e8df3857393da815e28cdf", IOM_DOC, "Halden HCP-350 IOM Rev D",
           "service_manual", 3, "p. 7, 8.4 Replacing the mechanical seal", revision="D")
CASE = cite("p_6ba270621506e02e89917314", SF_NA, "Salesforce cases NA", "case_export", 0,
            "Case 00041988")

answer = AnswerResponse(
    answer_id="ans_example_q04", dataset_version="ds_0026", status="answer", asset=FRS_P_0031,
    sentences=[
        Sentence(kind="statement", segments=text(
            "Use 38 N-m on the casing bolts, cross pattern, two passes."),
            citations=[SB_SUMMARY.passage_id, SB_TABLE.passage_id]),
        Sentence(kind="statement", segments=text(
            "FRS-P-0031 is serial HCP350-241187, inside the revised-casing range of "
            "SB-2025-009 (HCP350-240001 and later)."), citations=[SB_TABLE.passage_id]),
        Sentence(kind="warning", segments=text(
            "Torquing this unit to 45 N-m cracked the gasket seat in June 2026 (case 00041988)."),
            citations=[CASE.passage_id]),
    ],
    citations={c.passage_id: c for c in (SB_SUMMARY, SB_TABLE, IOM, CASE)},
    conflicts=[Conflict(
        topic="Casing bolt torque",
        sides=[ConflictSide(statement="38 N-m for HCP350-240001 and later",
                            citations=[SB_TABLE.passage_id]),
               ConflictSide(statement="45 N-m", citations=[IOM.passage_id])],
        preferred=0,
        reason="The bulletin covers this serial and outranks the manual; 45 N-m applies only "
               "to serials before HCP350-240001.")],
    notices=[Notice(kind="bulletin", text="SB-2025-009 applies to this unit.",
                    citations=[SB_TABLE.passage_id])])

WIKI_E31 = cite("p_f305f74b3d432a456bfd9221", PLAYBOOK,
                "Compressor Troubleshooting Playbook", "wiki", 4,
                "E-31 VFD overcurrent (VRS-110 only)")
restricted = AnswerResponse(
    answer_id="ans_example_q06", dataset_version="ds_0026", status="restricted",
    asset=ResolvedAsset(asset_id="TAC-C-0143", model="VRS-110", serial="VRS110-240210",
                        firmware="5.1", site="TAC", site_name="Tacoma Cold Storage", region="NA"),
    sentences=[
        Sentence(kind="statement", segments=text(
            "E-31 is a VFD overcurrent trip and can't be reset from the panel."),
            citations=[WIKI_E31.passage_id]),
        Sentence(kind="warning", segments=text(
            "The reset is done under HV-PROC-07 by HV-certified technicians. You're not "
            "cleared for that procedure, so the steps aren't shown."),
            citations=[WIKI_E31.passage_id]),
    ],
    citations={WIKI_E31.passage_id: WIKI_E31},
    restricted=Restricted(procedure="HV-PROC-07", missing_groups=["cert-hv"],
                          citations=[WIKI_E31.passage_id]),
    work_order_suggestion=WorkOrderSuggestion(
        asset_id="TAC-C-0143", fault_code="E-31", summary="E-31 VFD overcurrent trip, needs "
        "reset under HV-PROC-07", required_certification=["cert-hv"],
        citations=[WIKI_E31.passage_id]))

abstain = AnswerResponse(
    answer_id="ans_example_q07", dataset_version="ds_0026", status="abstain",
    abstain_reason="no_permitted_source",
    notices=[Notice(kind="no_answer", text="No source you can see covers the BX-20 warranty. "
                    "The BX-12 warranty does not apply to the BX-20.")])

clarify = AnswerResponse(
    answer_id="ans_example_clarify", dataset_version="ds_0026", status="clarify",
    clarification=Clarification(
        question="Which HCP-350 at Fresno?",
        options=[ClarifyOption(asset_id="FRS-P-0012", label="FRS-P-0012 (HCP350-221034)"),
                 ClarifyOption(asset_id="FRS-P-0031", label="FRS-P-0031 (HCP350-241187)")]))

HCP200 = cite("p_7a891cda95ff12c33c8caaa5", HCP200_DOC,
              "Halden HCP-200 Betriebsanleitung 1998 (scan)", "service_manual", 3,
              "p. 3, 3 Technische Daten / Technical data", revision="A", ocr=True,
              translated=True)
unverified = AnswerResponse(
    answer_id="ans_example_unverified", dataset_version="ds_0026", status="answer",
    sentences=[Sentence(kind="statement", segments=[
        Segment(kind="text", text="The rated head is "),
        Segment(kind="unverified", review_item_id="r_0000000000000000", page=3,
                page_image_passage_id=HCP200.passage_id),
        Segment(kind="text", text=".")], citations=[HCP200.passage_id])],
    citations={HCP200.passage_id: HCP200},
    notices=[Notice(kind="unverified_value", text="One value could not be verified from the "
                    "scan. Check scanned page 3.", citations=[HCP200.passage_id])])

for name, r in [("answer", answer), ("restricted", restricted), ("abstain", abstain),
                ("clarify", clarify), ("unverified", unverified)]:
    r.check()
    (HERE / f"{name}.json").write_text(r.model_dump_json(indent=2) + "\n")
(HERE / "answer-response.schema.json").write_text(
    json.dumps(AnswerResponse.model_json_schema(), indent=2) + "\n")
print("ok")
