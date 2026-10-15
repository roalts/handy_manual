"""Pure work-order rules (specs/contracts/work-orders-audit.md). No I/O here."""
import hashlib
import re
from collections.abc import Iterable
from datetime import datetime

from copilot_contracts.answer import PartLine

LEAD_GROUP = "role-lead"
REGION_GROUP = {"NA": "region-na", "EU": "region-eu"}
TARGET_SYSTEM = {"NA": "maintpro", "EU": "servio"}
REF_PREFIX = {"maintpro": "MP", "servio": "SV"}
EDITABLE = frozenset({"summary", "work_steps", "priority", "fault_code", "parts",
                      "needs_specialist", "return_visit"})
NO_APPROVER = "no eligible approver"
CERT_PREFIX = "cert-"

_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def target_system(region: str | None) -> str | None:
    """System a region's work orders go to (MaintPro for NA, Servio for EU), or None."""
    return TARGET_SYSTEM.get(region or "")


def approval_needs(parts: list, required_certification: list[str], campaign_code: str | None,
                   needs_specialist: bool = False, return_visit: bool = False) -> list[str]:
    """Why a draft needs approval, in a fixed order; empty when it doesn't."""
    reasons = []
    if parts:
        reasons.append("parts")
    if required_certification:
        reasons.append("certification")
    if campaign_code:
        reasons.append("campaign")
    if needs_specialist:
        reasons.append("specialist")
    if return_visit:
        reasons.append("return visit")
    return reasons


def certifications(groups: Iterable[str]) -> list[str]:
    """Only certification groups belong in required_certification, not family or region."""
    return [g for g in groups if g.startswith(CERT_PREFIX)]


def is_lead_for(groups: Iterable[str], region: str) -> bool:
    """Team lead holding the region's group."""
    groups = set(groups)
    return LEAD_GROUP in groups and REGION_GROUP.get(region) in groups


def valid_key(key: str | None) -> bool:
    """Keys name outbox files, so only a safe file-name alphabet is accepted."""
    return bool(key) and _KEY.fullmatch(key) is not None


def external_ref(system: str, key: str) -> str:
    """Fake reference, stable for a key so a lost response can be replayed."""
    n = int.from_bytes(hashlib.sha256(f"{system}:{key}".encode()).digest()[:8], "big")
    return f"{REF_PREFIX[system]}-{n % 10**7:07d}"


def required_groups_of(alternatives: list[frozenset[str]]) -> set[str]:
    """Groups a procedure needs whichever access alternative is used."""
    return set(frozenset.intersection(*alternatives)) if alternatives else set()


def dedupe(items: Iterable[str]) -> list[str]:
    """Items without repeats, in first-seen order."""
    return list(dict.fromkeys(items))


def outbox_record(*, system: str, key: str, ref: str, draft: dict, asset: dict,
                  submitted_by: str, submitted_at: datetime) -> dict:
    """What would be sent, in the field names of the corpus exports of each system."""
    parts = [PartLine.model_validate(p) for p in draft["parts"]]
    notes = draft["summary"] + (f"\n\n{draft['work_steps']}" if draft["work_steps"] else "")
    if system == "maintpro":
        work_order = {
            "WO_No": ref, "Date": submitted_at.strftime("%m/%d/%Y"), "Site": asset["site"],
            "Asset": asset["asset_id"], "Model": asset["model"], "Serial": asset["serial"],
            "Event_Type": "CM", "Fault": draft["fault_code"] or "", "Tech": "", "Notes": notes,
            "Parts": "; ".join(f"{p.part_number} x{p.quantity}" for p in parts),
            "Status": "OPEN",
        }
    else:
        work_order = {
            "werkorder": ref, "datum": submitted_at.strftime("%d-%m-%Y"),
            "object": asset["asset_id"], "locatie": asset["site_name"], "type": "Storing",
            "storingscode": draft["fault_code"] or "", "omschrijving": notes, "monteur": "",
            "onderdelen": ", ".join(f"{p.quantity}x {p.part_number}" for p in parts),
            "status": "Open",
        }
    return {
        "system": system,
        "idempotency_key": key,
        "external_ref": ref,
        "work_order": work_order,
        "copilot": {
            "draft_id": draft["draft_id"], "answer_id": draft["answer_id"],
            "requested_by": draft["created_by"], "submitted_by": submitted_by,
            "submitted_at": submitted_at.isoformat(), "approved_by": draft["decided_by"],
            "priority": draft["priority"],
            "required_certification": list(draft["required_certification"]),
            "campaign_code": draft["campaign_code"],
            "needs_specialist": draft.get("needs_specialist", False),
            "return_visit": draft.get("return_visit", False),
            "citations": list(draft["citations"]),
        },
    }
