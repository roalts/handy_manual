"""Read access to the published dataset, only through `serving.*` (contracts README rule 2).

Every corpus read takes the user's groups and is filtered inside the database before ranking.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

import psycopg
from pgvector.psycopg import register_vector

from copilot_ingest.settings import get_settings

_P_COLS = ("passage_id, doc_id, role, parent_passage_id, anchor, heading_path, block_types, lang,"
           " text_original, text_en, fault_codes, part_numbers, asset_ids, serials, case_numbers,"
           " models, restricted_tags, ocr, page_image, possibly_stale")
IDENTIFIER_FETCH = 5000


@dataclass(frozen=True)
class DatasetInfo:
    dataset_version: str
    embedding_model: str
    embedding_dims: int


@dataclass(frozen=True)
class ProcedureAlt:
    name: str
    title: str
    doc_id: str
    required_groups: frozenset[str]


@dataclass(frozen=True)
class Asset:
    asset_id: str
    model: str
    serial: str
    site: str
    site_name: str
    region: str
    firmware: str | None = None


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    doc_type: str
    authority_tier: int
    models: tuple[str, ...] = ()
    revision: str | None = None
    issue_date: date | None = None
    status: str = "active"


@dataclass
class Passage:
    passage_id: str
    doc_id: str
    text_original: str
    role: str = "standard"
    parent_passage_id: str | None = None
    anchor: dict = field(default_factory=dict)
    heading_path: list[str] = field(default_factory=list)
    block_types: list[str] = field(default_factory=list)
    lang: str | None = "en"
    text_en: str | None = None
    fault_codes: list[str] = field(default_factory=list)
    part_numbers: list[str] = field(default_factory=list)
    asset_ids: list[str] = field(default_factory=list)
    serials: list[str] = field(default_factory=list)
    case_numbers: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    restricted_tags: list[str] = field(default_factory=list)
    ocr: str = "none"
    page_image: str | None = None
    possibly_stale: bool = False

    @property
    def text(self) -> str:
        """English text for the model; the original when it is already English."""
        return self.text_en or self.text_original

    @property
    def all_text(self) -> str:
        """Original and English text together, for matching tokens in either language."""
        return self.text_original + "\n" + (self.text_en or "")


@dataclass(frozen=True)
class BulletinStatus:
    doc_id: str
    asset_id: str
    status: str
    rule_id: str | None
    reason: str | None
    campaign_code: str | None = None
    quote: str | None = None
    page: int | None = None


@dataclass(frozen=True)
class Relation:
    from_doc: str
    to_doc: str
    relation: str


@dataclass(frozen=True)
class Event:
    event_id: str
    asset_id: str
    event_date: date
    event_type: str
    fault_code: str | None
    notes: str
    parts: tuple[str, ...]
    passage_id: str | None


class Serving(Protocol):
    def dataset_info(self) -> DatasetInfo:
        """Version and embedding settings of the published dataset."""
        ...
    def restricted_procedures(self) -> list[ProcedureAlt]:
        """Restricted procedures, one entry per access alternative."""
        ...
    def assets(self) -> list[Asset]:
        """All fleet assets."""
        ...
    def asset_aliases(self) -> dict[str, str]:
        """Alternative asset IDs (such as legacy IDs) mapped to the asset ID."""
        ...
    def site_aliases(self) -> dict[str, str]:
        """Site alias to site code."""
        ...
    def relations(self) -> list[Relation]:
        """Relations between documents (supersedes, possibly_stale_vs)."""
        ...
    def bulletin_statuses(self, asset_id: str) -> list[BulletinStatus]:
        """Bulletin statuses of one asset, with the deciding rule's campaign, quote and page."""
        ...
    def documents(self, groups: frozenset[str]) -> dict[str, Document]:
        """Documents the groups may see, by doc ID."""
        ...
    def passages(self, groups: frozenset[str], ids: list[str]) -> dict[str, Passage]:
        """Passages among `ids` the groups may see, by passage ID; others are absent."""
        ...
    def doc_passages(self, groups: frozenset[str], doc_id: str) -> list[Passage]:
        """Passages of one document the groups may see."""
        ...
    def identifier_search(self, groups: frozenset[str], ids: list[str], k: int
                          ) -> list[str]:
        """Visible passage IDs matching the most of `ids`, best first; at most `k`."""
        ...
    def keyword_search(self, groups: frozenset[str], query: str, k: int) -> list[str]:
        """Visible passage IDs by full-text rank; at most `k`."""
        ...
    def vector_search(self, groups: frozenset[str], embedding: list[float], k: int
                      ) -> list[str]:
        """Visible passage IDs nearest to the embedding; at most `k`."""
        ...
    def visible_passages(self, groups: frozenset[str], ids: list[str]) -> set[str]:
        """The IDs in `ids` the groups may see."""
        ...
    def events(self, groups: frozenset[str], asset_id: str) -> list[Event]:
        """Service events of one asset the groups may see, oldest first."""
        ...
    def restricted_markers(self) -> dict[str, tuple[str, ...]]:
        """Leak-guard markers per restricted procedure name."""
        ...
    def hidden_exists(self, groups: frozenset[str], ids: list[str],
                      embedding: list[float] | None, max_distance: float | None) -> bool:
        """Whether passages hidden from the groups share `ids` (and lie within `max_distance` of
        the embedding when given); reveals existence only."""
        ...


def _g(groups: frozenset[str]) -> list[str]:
    """Groups as a sorted list, for a SQL array parameter."""
    return sorted(groups)


class PgServing:
    """`Serving` over the local Postgres database."""

    def __init__(self, url: str | None = None) -> None:
        """Connect to `url` (default: the configured database) and register pgvector types."""
        # No server-side prepared statements: after a few executions PostgreSQL may switch a
        # prepared search to a generic plan, which returns different passages for the same
        # question, so evidence and cache keys would depend on how long the process has run.
        self.conn = psycopg.connect(url or get_settings().database_url, autocommit=True,
                                    prepare_threshold=None)
        register_vector(self.conn)

    def _rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        """All rows of a query."""
        return self.conn.execute(sql, params).fetchall()

    def dataset_info(self) -> DatasetInfo:
        """Version and embedding settings from `serving.dataset_info()`."""
        row = self._rows("SELECT dataset_version, embedding_model, embedding_dims"
                         " FROM serving.dataset_info()")[0]
        return DatasetInfo(*row)

    def restricted_procedures(self) -> list[ProcedureAlt]:
        """One `ProcedureAlt` per access alternative of each restricted procedure."""
        return [ProcedureAlt(n, t, d, frozenset(g)) for n, t, d, g in self._rows(
            "SELECT name, title, doc_id, required_groups FROM serving.restricted_procedures")]

    def assets(self) -> list[Asset]:
        """All fleet assets."""
        return [Asset(*r) for r in self._rows(
            "SELECT asset_id, model, serial, site, site_name, region, firmware"
            " FROM serving.assets")]

    def asset_aliases(self) -> dict[str, str]:
        """Alias to asset ID."""
        return dict(self._rows("SELECT alias, asset_id FROM serving.asset_aliases"))

    def site_aliases(self) -> dict[str, str]:
        """Site alias to site code."""
        return dict(self._rows("SELECT alias, site FROM serving.site_aliases"))

    def relations(self) -> list[Relation]:
        """All document relations."""
        return [Relation(*r) for r in self._rows(
            "SELECT from_doc, to_doc, relation FROM serving.document_relations")]

    def bulletin_statuses(self, asset_id: str) -> list[BulletinStatus]:
        """Bulletin statuses of one asset, with the deciding rule's campaign, quote and page."""
        return [BulletinStatus(*r) for r in self._rows(
            "SELECT ba.doc_id, ba.asset_id, ba.status, ba.rule_id, ba.reason, r.campaign_code,"
            " r.quote, r.page FROM serving.bulletin_assets ba"
            " LEFT JOIN serving.bulletin_rules r USING (rule_id)"
            " WHERE ba.asset_id = %s ORDER BY ba.doc_id", (asset_id,))]

    def documents(self, groups: frozenset[str]) -> dict[str, Document]:
        """Documents visible to `groups`, by doc ID."""
        rows = self._rows(
            "SELECT doc_id, title, doc_type, authority_tier, models, revision, issue_date, status"
            " FROM serving.documents_for(%s)", (_g(groups),))
        return {r[0]: Document(r[0], r[1], r[2], r[3], tuple(r[4] or ()), r[5], r[6], r[7])
                for r in rows}

    def _passages(self, where: str, params: tuple) -> list[Passage]:
        """Visible passages matching a `WHERE` fragment; `params` start with the group list."""
        rows = self._rows(f"SELECT {_P_COLS} FROM serving.passages_for(%s) p WHERE {where}",
                          params)
        cols = [c.strip() for c in _P_COLS.split(",")]
        return [Passage(**dict(zip(cols, r, strict=True))) for r in rows]

    def passages(self, groups: frozenset[str], ids: list[str]) -> dict[str, Passage]:
        """Visible passages among `ids`, by passage ID; hidden or unknown IDs are absent."""
        if not ids:
            return {}
        found = self._passages("p.passage_id = ANY(%s)", (_g(groups), list(ids)))
        return {p.passage_id: p for p in found}

    def doc_passages(self, groups: frozenset[str], doc_id: str) -> list[Passage]:
        """Visible passages of one document."""
        return self._passages("p.doc_id = %s", (_g(groups), doc_id))

    def identifier_search(self, groups, ids, k):
        """Visible passage IDs matching the most of `ids`, ties by passage ID; at most `k`."""
        if not ids:
            return []
        # The function orders by match count only; many passages tie, so which ones fill the
        # last places would depend on the query plan. Fetch all and break ties by passage ID.
        rows = self._rows("SELECT passage_id, matches FROM serving.identifier_search(%s, %s, %s)",
                          (_g(groups), list(ids), IDENTIFIER_FETCH))
        return [pid for pid, _ in sorted(rows, key=lambda r: (-r[1], r[0]))[:k]]

    def keyword_search(self, groups, query, k):
        """Visible passage IDs by full-text rank, at most `k`; none for a blank query."""
        if not query.strip():
            return []
        return [r[0] for r in self._rows(
            "SELECT passage_id FROM serving.keyword_search(%s, %s, %s)", (_g(groups), query, k))]

    def restricted_markers(self):
        """Leak-guard markers per procedure; `proposed` ones count too (fail closed)."""
        out: dict[str, list[str]] = {}
        for proc, marker in self._rows(
                "SELECT procedure, marker FROM serving.restricted_markers"
                " WHERE status IN ('approved', 'proposed')"):
            out.setdefault(proc, []).append(marker)
        return {k: tuple(sorted(v)) for k, v in out.items()}

    def hidden_exists(self, groups, ids, embedding, max_distance):
        """Whether a passage hidden from `groups` shares `ids` (and lies within `max_distance`
        of `embedding` when given); reveals existence only, never content."""
        import numpy as np

        return bool(self._rows(
            "SELECT serving.hidden_exists(%s, %s, %s, %s)",
            (_g(groups), ids,
             None if embedding is None else np.array(embedding, dtype=np.float32),
             max_distance))[0][0])

    def vector_search(self, groups, embedding, k):
        """Visible passage IDs nearest to `embedding`; at most `k`."""
        import numpy as np

        return [r[0] for r in self._rows(
            "SELECT passage_id FROM serving.vector_search(%s, %s, %s)",
            (_g(groups), np.array(embedding, dtype=np.float32), k))]

    def visible_passages(self, groups, ids):
        """The IDs in `ids` that `groups` may see (`serving.can_see`)."""
        if not ids:
            return set()
        return {r[0] for r in self._rows(
            "SELECT id FROM unnest(%s::text[]) id WHERE serving.can_see('passage', id, %s)",
            (list(ids), _g(groups)))}

    def events(self, groups, asset_id):
        """Service events of one asset visible to `groups`, oldest first; notes in English when
        translated."""
        rows = self._rows(
            "SELECT event_id, asset_id, event_date, event_type, fault_code,"
            " coalesce(notes_en, notes_original, ''), parts, passage_id"
            " FROM serving.events_for(%s) WHERE asset_id = %s ORDER BY event_date",
            (_g(groups), asset_id))
        return [Event(r[0], r[1], r[2], r[3], r[4], r[5], tuple(r[6] or ()), r[7]) for r in rows]
