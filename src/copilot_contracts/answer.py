"""Answer contract (specs/contracts/answer.md)."""
from datetime import date
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Identity(_Model):
    """Resolved by the API from the session, never from conversation content."""
    user_id: str
    name: str
    groups: frozenset[str]


class PreviousTurn(_Model):
    """The answer the new message follows. Carries no access: retrieval still uses the
    asker's groups, and the text is what the user already typed or was shown."""
    answer_id: str
    question: str = Field(min_length=1, max_length=2000)
    """`question_used` of that answer (or the asked text if it had none)."""
    asset_id: str | None = None


class AskRequest(_Model):
    question: str = Field(min_length=1, max_length=2000)
    asset_id: str | None = None
    """Set when the user picked an option from a clarification."""
    clarification_of: str | None = None
    """answer_id of the clarify response being answered."""
    previous: PreviousTurn | None = None
    """Set when the message follows an earlier answer in the same conversation."""


class Segment(_Model):
    """Text, or a withheld scanned value that must be shown as unverified and never filled in."""
    kind: Literal["text", "unverified"]
    text: str = ""
    review_item_id: str | None = None
    page: int | None = None
    page_image_passage_id: str | None = None


class Sentence(_Model):
    kind: Literal["statement", "step", "warning"]
    step_number: int | None = None
    segments: list[Segment]
    citations: list[str] = Field(min_length=1)
    """passage_ids, each a key of AnswerResponse.citations."""


class Citation(_Model):
    passage_id: str
    doc_id: str
    title: str
    doc_type: str
    revision: str | None
    issue_date: date | None
    authority_tier: int
    locator: str
    """Human label such as "p. 7, 8.4 Replacing the mechanical seal" or "Case 00041988"."""
    viewer_url: str
    superseded: bool = False
    possibly_stale: bool = False
    ocr: bool = False
    translated: bool = False


class ConflictSide(_Model):
    statement: str
    citations: list[str] = Field(min_length=1)


class Conflict(_Model):
    topic: str
    sides: list[ConflictSide] = Field(min_length=2)
    preferred: int | None
    """Index into sides chosen by code (applicability, then authority), or None if undecided."""
    reason: str


class Notice(_Model):
    kind: Literal["superseded", "possibly_stale", "bulletin", "check_on_site",
                  "unverified_value", "not_visible", "translated", "history", "no_answer"]
    """`not_visible` only with abstain_reason `not_visible`; other abstains use `no_answer`."""
    text: str
    citations: list[str] = []


class AssetBulletin(_Model):
    doc_id: str
    title: str
    status: Literal["affected", "in_campaign", "not_affected", "check_on_site"]
    campaign_code: str | None = None
    reason: str | None = None
    citations: list[str] = []


class ResolvedAsset(_Model):
    asset_id: str
    model: str
    serial: str
    firmware: str | None
    site: str
    site_name: str
    region: str
    bulletins: list[AssetBulletin] = []


class ClarifyOption(_Model):
    """Exactly one of `asset_id` (pick a machine) or `question` (resend this text instead,
    e.g. "did you mean HCP-200?") is set."""
    asset_id: str | None = None
    label: str
    question: str | None = None

    def model_post_init(self, _context) -> None:
        if (self.asset_id is None) == (self.question is None):
            raise ValueError("ClarifyOption needs exactly one of asset_id or question")


class Clarification(_Model):
    question: str
    options: list[ClarifyOption] = Field(min_length=1)
    """Machine choices come at least two at a time; a "did you mean" may offer one."""


class Restricted(_Model):
    procedure: str
    """Procedure name only, such as "HV-PROC-07". Never its content."""
    missing_groups: list[str] = Field(min_length=1)
    citations: list[str] = Field(min_length=1)
    """Visible passages that say the work is restricted."""


class PartLine(_Model):
    part_number: str
    quantity: int = 1


class WorkOrderSuggestion(_Model):
    """Prefill for a work-order draft. Every value comes from a cited passage or the asset."""
    asset_id: str | None = None
    """None when no single machine was resolved; the draft form then asks for one."""
    fault_code: str | None = None
    summary: str
    required_certification: list[str] = []
    parts: list[PartLine] = []
    campaign_code: str | None = None
    citations: list[str] = []


class AnswerResponse(_Model):
    answer_id: str
    dataset_version: str
    status: Literal["answer", "clarify", "abstain", "restricted"]
    asset: ResolvedAsset | None = None
    sentences: list[Sentence] = []
    citations: dict[str, Citation] = {}
    conflicts: list[Conflict] = []
    notices: list[Notice] = []
    clarification: Clarification | None = None
    restricted: Restricted | None = None
    abstain_reason: Literal["no_permitted_source", "not_visible", "unknown_asset",
                            "out_of_scope"] | None = None
    work_order_suggestion: WorkOrderSuggestion | None = None
    question_used: str | None = None
    """The standalone question actually answered, when it differs from the typed text
    (a follow-up rewritten with the previous turn). Clients send it back as
    `previous.question`."""
    timings_ms: dict[str, int] = {}

    def check(self) -> None:
        """Structural rules every producer must satisfy and every consumer may rely on."""
        cited = {c for s in self.sentences for c in s.citations}
        cited |= {c for x in self.conflicts for side in x.sides for c in side.citations}
        cited |= {c for n in self.notices for c in n.citations}
        if self.restricted:
            cited |= set(self.restricted.citations)
        if missing := cited - set(self.citations):
            raise ValueError(f"citations referenced but not listed: {sorted(missing)}")
        need = {"answer": self.sentences, "clarify": self.clarification,
                "restricted": self.restricted, "abstain": self.abstain_reason}
        if not need[self.status]:
            raise ValueError(f"status {self.status!r} without its payload")


class AnswerEngine(Protocol):
    def answer(self, identity: Identity, request: AskRequest) -> AnswerResponse: ...
