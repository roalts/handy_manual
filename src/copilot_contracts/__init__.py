"""Shared contracts between the answer engine, the answer API, the web client, work orders
and the evaluation harness, specified in specs/contracts/. A field change is a contract change."""
from copilot_contracts.answer import (
    AnswerEngine,
    AnswerResponse,
    AskRequest,
    AssetBulletin,
    Citation,
    Clarification,
    ClarifyOption,
    Conflict,
    ConflictSide,
    Identity,
    Notice,
    PartLine,
    PreviousTurn,
    ResolvedAsset,
    Restricted,
    Segment,
    Sentence,
    WorkOrderSuggestion,
)
from copilot_contracts.work_orders import AuditEvent, WorkOrderDraft

__all__ = [
    "AnswerEngine", "AnswerResponse", "AskRequest", "AssetBulletin", "AuditEvent", "Citation",
    "Clarification", "ClarifyOption", "Conflict", "ConflictSide", "Identity", "Notice",
    "PartLine", "PreviousTurn", "ResolvedAsset", "Restricted", "Segment", "Sentence",
    "WorkOrderDraft", "WorkOrderSuggestion",
]
