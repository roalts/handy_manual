from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

BlockType = Literal[
    "heading", "paragraph", "list_item", "procedure_step", "table", "record", "message", "warning"
]


class Anchor(BaseModel):
    page: int | None = None
    page_end: int | None = None
    section_path: list[str] = Field(default_factory=list)
    table: int | None = None
    record_id: str | None = None
    message_id: str | None = None

    def key(self) -> str:
        """JSON of the fields that are set; part of the passage ID hash."""
        return self.model_dump_json(exclude_none=True)


class Block(BaseModel):
    type: BlockType
    text: str
    anchor: Anchor
    heading_path: list[str] = Field(default_factory=list)
    lang: str | None = None
    header: list[str] | None = None  # tables only
    rows: list[list[str]] | None = None  # tables only
    fields: dict[str, Any] | None = None  # records and messages
    level: int | None = None  # headings only


class PageCoverage(BaseModel):
    page: int
    status: Literal["text", "scanned", "blank", "figure_only", "unrecoverable"]
    chars: int = 0


class ExtractResult(BaseModel):
    path: str
    fingerprint: str
    extractor: str
    extractor_version: str
    title: str | None = None
    blocks: list[Block] = Field(default_factory=list)
    pages: list[PageCoverage] = Field(default_factory=list)
    flags: dict[str, Any] = Field(default_factory=dict)
    records: list[dict[str, Any]] = Field(default_factory=list)  # tabular sources, raw rows


class SourceFile(BaseModel):
    path: str
    fingerprint: str | None
    size_bytes: int
    source_system: str | None
    required_groups: list[str] | None
    status: Literal["active", "quarantined", "partial", "removed"] = "active"
    changed: bool = True


class QuarantineRecord(BaseModel):
    path: str
    stage: str
    reason: Literal["no_access_rule", "unknown_group", "empty_file", "unreadable",
                    "unsupported_format"]
    detail: str = ""


class ReviewItem(BaseModel):
    kind: Literal["ocr_value_mismatch", "metadata_unverified", "restricted_borderline",
                  "marker_approval", "unresolved_link", "unknown_asset"]
    path: str | None
    anchor: dict[str, Any] | None = None
    field: str | None = None
    candidates: dict[str, Any] | list[Any] | None = None
    reason: str
    fingerprint: str = ""
    stage: str = ""


class Document(BaseModel):
    doc_id: str
    title: str | None
    doc_type: str
    authority_tier: int
    controlled: bool
    models: list[str] = Field(default_factory=list)
    revision: str | None = None
    issue_date: date | None = None
    languages: list[str] = Field(default_factory=list)
    status: Literal["active", "superseded", "partial"] = "active"
    missing_pages: list[int] = Field(default_factory=list)
    extractor_version: str
    origins: list[dict[str, Any]] = Field(default_factory=list)


class Passage(BaseModel):
    passage_id: str
    doc_id: str
    role: Literal["standard", "parent", "child"] = "standard"
    parent_passage_id: str | None = None
    anchor: Anchor
    heading_path: list[str] = Field(default_factory=list)
    block_types: list[str] = Field(default_factory=list)
    lang: str | None = None
    text_original: str
    text_en: str | None = None
    fault_codes: list[str] = Field(default_factory=list)
    part_numbers: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    serials: list[str] = Field(default_factory=list)
    case_numbers: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    restricted_tags: list[str] = Field(default_factory=list)
    restricted_groups: list[str] = Field(default_factory=list)
    ocr: Literal["none", "verified", "has_withheld_values"] = "none"
    page_image: str | None = None
    possibly_stale: bool = False
    fingerprint: str
    extractor_version: str


class Asset(BaseModel):
    asset_id: str
    model: str
    serial: str
    site: str
    site_name: str | None
    customer: str | None
    region: str
    install_date: date | None
    firmware: str | None
    oil_type: str | None
    contract_end: date | None


class ServiceEvent(BaseModel):
    event_id: str
    asset_id: str
    event_date: date
    event_type: Literal["inspection", "preventive", "corrective", "alarm", "firmware", "meter",
                        "fgas_check", "case"]
    fault_code: str | None
    status: Literal["completed", "open", "cancelled"]
    notes_original: str | None
    notes_en: str | None = None
    parts: list[str] = Field(default_factory=list)
    labor_hours: float | None = None
    run_hours: float | None = None
    technician: str | None = None
    sources: list[dict[str, Any]]
    required_groups: list[list[str]] = Field(default_factory=list)
    passage_id: str | None = None


class BulletinRule(BaseModel):
    """One applicability row of a bulletin: which units, under which conditions, what outcome."""
    rule_id: str
    doc_id: str
    model: str
    serial_from: str | None = None  # inclusive; None = open-ended
    serial_to: str | None = None  # inclusive; None = open-ended
    firmware_condition: str | None = None  # verbatim, e.g. "5.0.0 to 5.0.3"
    market_condition: str | None = None  # verbatim, e.g. "EU deliveries"
    variant_condition: str | None = None  # verbatim; not decidable from the fleet register
    outcome: Literal["affected", "in_campaign", "not_affected"]
    campaign_code: str | None = None
    action_summary: str | None = None
    quote: str
    page: int | None = None


class BulletinAsset(BaseModel):
    doc_id: str
    asset_id: str
    status: Literal["affected", "in_campaign", "not_affected", "check_on_site"]
    rule_id: str | None = None
    reason: str


class Relation(BaseModel):
    from_doc: str
    to_doc: str
    relation: Literal["supersedes", "possibly_stale_vs", "duplicate_of", "pairs_language_with"]
    quote: str | None = None
    page: int | None = None
