"""In-memory `WorkOrders` and `AuditLog` (copilot_contracts.services).

Used by the API tests, and by the development server until `copilot_workorders` (005) exists.
They follow work-orders-audit.md closely enough for the client to work; 005 is the real
implementation and owns the rules.
"""
import threading
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from copilot_api.identity import Directory
from copilot_contracts import AuditEvent, Identity, PartLine, WorkOrderDraft, WorkOrderSuggestion
from copilot_contracts.services import (
    Forbidden,
    InvalidRequest,
    InvalidState,
    NotEditable,
    NotFound,
    NotVisible,
)

EDITABLE = {"summary", "work_steps", "priority", "fault_code", "parts", "needs_specialist",
            "return_visit"}
TARGET = {"NA": "maintpro", "EU": "servio"}

Visible = Callable[[frozenset[str], Iterable[str]], set[str]]


def _now() -> datetime:
    """The current time in UTC."""
    return datetime.now(UTC)


class MemoryAuditLog:
    def __init__(self, visible: Visible | None = None) -> None:
        """`visible` hides events citing passages a reader can't see; without it none are hidden."""
        self.events: list[AuditEvent] = []
        self._visible = visible
        self._lock = threading.Lock()

    def record(self, event: AuditEvent) -> None:
        """Append the event unless one with its event_id is already recorded."""
        with self._lock:
            if all(e.event_id != event.event_id for e in self.events):
                self.events.append(event)

    def visible_events(self, identity: Identity, *, answer_id: str | None = None,
                       draft_id: str | None = None) -> list[AuditEvent]:
        """Events, optionally for one answer or draft, except those citing passages hidden from
        `identity`."""
        out = []
        for e in list(self.events):
            if answer_id and e.answer_id != answer_id or draft_id and e.draft_id != draft_id:
                continue
            if self._visible and set(e.passage_ids) - self._visible(identity.groups,
                                                                    e.passage_ids):
                continue
            out.append(e)
        return out


class MemoryWorkOrders:
    def __init__(self, directory: Directory, region_of: Callable[[str], str | None],
                 visible: Visible, audit: MemoryAuditLog, dataset_version: Callable[[], str]
                 ) -> None:
        """`region_of` gives an asset's region, or None for an unknown asset."""
        self.directory = directory
        self.region_of = region_of
        self.visible = visible
        self.audit = audit
        self.dataset_version = dataset_version
        self.drafts: dict[str, WorkOrderDraft] = {}
        self.submissions: dict[str, WorkOrderDraft] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ rules

    def _sees_all(self, groups: frozenset[str], d: WorkOrderDraft) -> bool:
        """Whether `groups` can see every passage the draft cites."""
        return not set(d.citations) - self.visible(groups, d.citations)

    def _approvers(self, d: WorkOrderDraft) -> list[str]:
        """Leads of the asset's region, other than the creator, who can see every citation."""
        region = "region-" + (self.region_of(d.asset_id) or "").lower()
        return [u.user_id for u in self.directory.users()
                if {"role-lead", region} <= u.groups and u.user_id != d.created_by
                and self._sees_all(u.groups, d)]

    def _refresh(self, d: WorkOrderDraft) -> WorkOrderDraft:
        """The draft with approval reasons and eligible approvers recomputed from current users."""
        reasons = [r for r, needed in (("parts", d.parts),
                                       ("certification", d.required_certification),
                                       ("campaign", d.campaign_code),
                                       ("specialist", d.needs_specialist),
                                       ("return visit", d.return_visit)) if needed]
        approvers = self._approvers(d) if reasons else []
        if reasons and not approvers:
            reasons.append("no eligible approver")
        return d.model_copy(update={"approval_reasons": reasons, "eligible_approvers": approvers})

    def _event(self, identity: Identity, kind: str, d: WorkOrderDraft, outcome: str,
               details: dict | None = None) -> None:
        """Audit an action on the draft, tagged with the current dataset version."""
        self.audit.record(AuditEvent(
            event_id=uuid.uuid4().hex, at=_now(), user_id=identity.user_id, kind=kind,
            answer_id=d.answer_id, draft_id=d.draft_id, dataset_version=self.dataset_version(),
            passage_ids=list(d.citations), outcome=outcome, details=details or {}))

    def _visible_draft(self, identity: Identity, draft_id: str, audit_denial: bool = True
                       ) -> WorkOrderDraft:
        """The refreshed draft, for its creator or a region lead, if they see every citation.
        Raises NotFound or NotVisible; the denial is audited unless `audit_denial` is False."""
        d = self.drafts.get(draft_id)
        if d is None:
            raise NotFound(f"no draft {draft_id}")
        d = self._refresh(d)
        lead = identity.user_id in self._approvers(d) or (
            {"role-lead", "region-" + (self.region_of(d.asset_id) or "").lower()}
            <= identity.groups and self._sees_all(identity.groups, d))
        if not (d.created_by == identity.user_id or lead) or not self._sees_all(
                identity.groups, d):
            if audit_denial:
                self._event(identity, "access_denied", d, "not_visible")
            raise NotVisible("not visible to you")
        return d

    def _save(self, d: WorkOrderDraft) -> WorkOrderDraft:
        """Store the draft with refreshed approval fields and return it."""
        d = self._refresh(d)
        self.drafts[d.draft_id] = d
        return d

    # ------------------------------------------------------------------ WorkOrders

    def create(self, identity: Identity, answer_id: str | None, suggestion: WorkOrderSuggestion,
               *, summary: str | None = None, work_steps: str | None = None,
               priority: str | None = None, fault_code: str | None = None,
               parts: list[PartLine] | None = None, asset_id: str | None = None
               ) -> WorkOrderDraft:
        """A new draft from an answer's suggestion; the asset's region picks the target system."""
        asset_id = asset_id or suggestion.asset_id
        if not asset_id:
            raise InvalidRequest("asset_id is required")
        region = self.region_of(asset_id)
        if region not in TARGET:
            raise InvalidRequest(f"unknown asset {asset_id}")
        if set(suggestion.citations) - self.visible(identity.groups, suggestion.citations):
            raise NotVisible("a cited passage is not visible to you")
        if priority is not None and priority not in ("low", "medium", "high"):
            raise InvalidRequest("priority must be low, medium or high")
        with self._lock:
            d = WorkOrderDraft(
                draft_id="wo_" + uuid.uuid4().hex[:12], created_by=identity.user_id,
                created_at=_now(), answer_id=answer_id, asset_id=asset_id,
                target_system=TARGET[region],
                fault_code=fault_code if fault_code is not None else suggestion.fault_code,
                summary=summary or suggestion.summary, work_steps=work_steps or "",
                required_certification=list(suggestion.required_certification),
                parts=list(parts if parts is not None else suggestion.parts),
                campaign_code=suggestion.campaign_code, priority=priority or "medium",
                citations=list(suggestion.citations), idempotency_key=str(uuid.uuid4()))
            d = self._save(d)
            self._event(identity, "draft_created", d, "draft")
            return d

    def get(self, identity: Identity, draft_id: str) -> WorkOrderDraft:
        """The draft, if visible to `identity`; a denial is audited."""
        return self._visible_draft(identity, draft_id)

    def list_visible(self, identity: Identity, *, mine: bool = False) -> list[WorkOrderDraft]:
        """Drafts visible to `identity` (its own with `mine`), newest first; denials not audited."""
        out = []
        for draft_id, d in list(self.drafts.items()):
            if mine and d.created_by != identity.user_id:
                continue
            try:
                out.append(self._visible_draft(identity, draft_id, audit_denial=False))
            except NotVisible:
                pass
        return sorted(out, key=lambda d: d.created_at, reverse=True)

    def edit(self, identity: Identity, draft_id: str, changes: dict) -> WorkOrderDraft:
        """Apply the creator's changes to a draft or rejected draft; the result is a draft again."""
        with self._lock:
            d = self._visible_draft(identity, draft_id)
            if d.created_by != identity.user_id:
                raise Forbidden("only the creator can edit a draft")
            if bad := set(changes) - EDITABLE:
                raise InvalidRequest(f"not editable: {', '.join(sorted(bad))}")
            if d.status not in ("draft", "rejected"):
                raise NotEditable(f"draft is {d.status}")
            before = {k: getattr(d, k) for k in changes}
            try:
                new = WorkOrderDraft.model_validate(
                    {**d.model_dump(), **changes, "status": "draft"})
            except ValueError as e:
                raise InvalidRequest(str(e)) from e
            new = self._save(new)
            self._event(identity, "draft_edited", new, new.status, {
                "before": {k: _plain(v) for k, v in before.items()},
                "after": {k: _plain(getattr(new, k)) for k in changes}})
            return new

    def request_approval(self, identity: Identity, draft_id: str) -> WorkOrderDraft:
        """Move the creator's draft to pending_approval; InvalidState if no one can approve it."""
        with self._lock:
            d = self._visible_draft(identity, draft_id)
            if d.created_by != identity.user_id:
                raise Forbidden("only the creator can request approval")
            if d.status != "draft" or not d.eligible_approvers:
                raise InvalidState("; ".join(d.approval_reasons) or "no approval needed")
            d = self._save(d.model_copy(update={"status": "pending_approval"}))
            self._event(identity, "draft_edited", d, "pending_approval")
            return d

    def _decide(self, identity: Identity, draft_id: str, note: str | None, approve: bool
                ) -> WorkOrderDraft:
        """Approve or reject a pending draft as one of its eligible approvers."""
        with self._lock:
            d = self._visible_draft(identity, draft_id)
            if identity.user_id not in d.eligible_approvers:
                raise Forbidden("you can't approve this draft")
            if d.status != "pending_approval":
                raise InvalidState(f"draft is {d.status}")
            d = self._save(d.model_copy(update={
                "status": "approved" if approve else "rejected", "decided_by": identity.user_id,
                "decided_at": _now(), "decision_note": note or None}))
            self._event(identity, "draft_approved" if approve else "draft_rejected", d,
                        d.status, {"note": note})
            return d

    def approve(self, identity: Identity, draft_id: str, note: str | None) -> WorkOrderDraft:
        """Approve a pending draft."""
        return self._decide(identity, draft_id, note, True)

    def reject(self, identity: Identity, draft_id: str, note: str | None) -> WorkOrderDraft:
        """Reject a pending draft."""
        return self._decide(identity, draft_id, note, False)

    def submit(self, identity: Identity, draft_id: str, *, confirm: bool,
               idempotency_key: str) -> WorkOrderDraft:
        """Mark an approved draft, or one needing no approval, submitted with a fake external ref.
        A repeated idempotency key returns the earlier submission unchanged."""
        if confirm is not True:
            raise InvalidRequest("confirm must be true")
        if not idempotency_key:
            raise InvalidRequest("Idempotency-Key is required")
        with self._lock:
            d = self._visible_draft(identity, draft_id)
            if idempotency_key in self.submissions:
                return self.submissions[idempotency_key]
            if d.created_by != identity.user_id:
                raise Forbidden("only the creator can submit")
            ready = d.status == "approved" or (d.status == "draft" and not d.approval_reasons)
            if not ready:
                raise InvalidState("approval needed before submit")
            prefix = "MP" if d.target_system == "maintpro" else "SV"
            d = self._save(d.model_copy(update={
                "status": "submitted",
                "external_ref": f"{prefix}-{uuid.uuid4().int % 10**7:07d}"}))
            self.submissions[idempotency_key] = d
            self._event(identity, "draft_submitted", d, "submitted",
                        {"external_ref": d.external_ref, "idempotency_key": idempotency_key})
            return d


def _plain(v):
    """A field value for audit details, with lists of models turned into lists of dicts."""
    if isinstance(v, list):
        return [x.model_dump() if hasattr(x, "model_dump") else x for x in v]
    return v
