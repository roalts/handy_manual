"""Work-order and audit contract (specs/contracts/work-orders-audit.md)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from copilot_contracts.answer import PartLine


class WorkOrderDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    created_by: str
    created_at: datetime
    answer_id: str | None
    asset_id: str
    target_system: Literal["maintpro", "servio"]
    """MaintPro for NA sites, Servio for EU sites, from the asset's region."""
    fault_code: str | None = None
    summary: str = Field(min_length=1)
    work_steps: str = ""
    required_certification: list[str] = []
    """cert-* groups only. Groups added by rule from cited restricted procedures are never
    removed, by edits or otherwise."""
    parts: list[PartLine] = []
    campaign_code: str | None = None
    priority: Literal["low", "medium", "high"] = "medium"
    needs_specialist: bool = False
    return_visit: bool = False
    citations: list[str] = []
    """A user may see the draft only if they can currently see every cited passage."""
    status: Literal["draft", "pending_approval", "approved", "rejected", "submitted"] = "draft"
    approval_reasons: list[str] = []
    """Why approval is needed: parts, certification, specialist, return visit."""
    eligible_approvers: list[str] = []
    """User IDs who may approve now; empty with "no eligible approver" in approval_reasons."""
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    idempotency_key: str
    external_ref: str | None = None


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    at: datetime
    user_id: str
    kind: Literal["answer", "source_view", "draft_created", "draft_edited", "draft_approved",
                  "draft_rejected", "draft_submitted", "access_denied"]
    answer_id: str | None = None
    draft_id: str | None = None
    dataset_version: str | None = None
    passage_ids: list[str] = []
    outcome: str
    details: dict = {}
