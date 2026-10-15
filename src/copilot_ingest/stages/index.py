"""Write one dataset version (ds_NNNN): documents, passages, access alternatives, history."""
import json
from dataclasses import dataclass, field

from psycopg.types.json import Jsonb

from copilot_ingest.models import (
    Asset,
    BulletinAsset,
    BulletinRule,
    Document,
    Passage,
    Relation,
    ServiceEvent,
)

VERSION = "index-2"


@dataclass
class Dataset:
    documents: dict[str, Document] = field(default_factory=dict)
    passages: dict[str, Passage] = field(default_factory=dict)
    assets: dict[str, Asset] = field(default_factory=dict)
    asset_aliases: dict[str, tuple[str, str]] = field(default_factory=dict)
    site_aliases: dict[str, str] = field(default_factory=dict)
    events: list[ServiceEvent] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    bulletin_rules: list[BulletinRule] = field(default_factory=list)
    bulletin_assets: list[BulletinAsset] = field(default_factory=list)
    # passage_id -> list of alternatives; filled by compute_access
    passage_access: dict[str, list[list[str]]] = field(default_factory=dict)
    # passages created from events carry the event's alternatives
    event_passages: dict[str, str] = field(default_factory=dict)  # passage_id -> event_id


def compute_access(ds: Dataset) -> None:
    """Effective alternatives: each origin's rule plus the passage's restricted groups."""
    events = {e.event_id: e for e in ds.events}
    for pid, p in ds.passages.items():
        if pid in ds.event_passages:
            alts = events[ds.event_passages[pid]].required_groups
        else:
            alts = [o["required_groups"] for o in ds.documents[p.doc_id].origins]
        restricted = set(p.restricted_groups)
        uniq = sorted({tuple(sorted(set(a) | restricted)) for a in alts})
        ds.passage_access[pid] = [list(a) for a in uniq]


def _alternatives_rows(object_type: str, object_id: str, alts: list[list[str]]):
    """access_alternatives rows for one object, numbered in the given order."""
    return [(object_type, object_id, i, sorted(a)) for i, a in enumerate(alts)]


def write(conn, schema: str, ds: Dataset, embeddings: dict[str, list[float]] | None) -> dict:
    """Insert the dataset into `schema` and return row counts. Does not commit; expects
    `compute_access` to have filled `ds.passage_access`."""
    s = schema
    embeddings = embeddings or {}
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO {s}.documents (doc_id, title, doc_type, authority_tier, controlled,"
            " models, revision, issue_date, languages, status, missing_pages, extractor_version)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(d.doc_id, d.title, d.doc_type, d.authority_tier, d.controlled, d.models,
              d.revision, d.issue_date, d.languages, d.status, d.missing_pages,
              d.extractor_version) for d in ds.documents.values()])
        cur.executemany(
            f"INSERT INTO {s}.document_origins (doc_id, path, fingerprint, source_system,"
            " required_groups) VALUES (%s,%s,%s,%s,%s)",
            [(d.doc_id, o["path"], o["fingerprint"], o["source_system"], o["required_groups"])
             for d in ds.documents.values() for o in d.origins])
        doc_alts = []
        for d in ds.documents.values():
            uniq = sorted({tuple(sorted(o["required_groups"])) for o in d.origins})
            doc_alts += _alternatives_rows("document", d.doc_id, [list(a) for a in uniq])

        rows = []
        for p in ds.passages.values():
            searchable = " ".join([" ".join(p.heading_path), p.text_original, p.text_en or ""])
            rows.append((p.passage_id, p.doc_id, p.role, p.parent_passage_id,
                         Jsonb(json.loads(p.anchor.model_dump_json(exclude_none=True))),
                         p.heading_path, p.block_types, p.lang, p.text_original, p.text_en,
                         p.fault_codes, p.part_numbers, p.asset_ids, p.serials, p.case_numbers,
                         p.models, p.restricted_tags, p.ocr, p.page_image, p.possibly_stale,
                         searchable, embeddings.get(p.passage_id), p.fingerprint,
                         p.extractor_version))
        cur.executemany(
            f"INSERT INTO {s}.passages (passage_id, doc_id, role, parent_passage_id, anchor,"
            " heading_path, block_types, lang, text_original, text_en, fault_codes,"
            " part_numbers, asset_ids, serials, case_numbers, models, restricted_tags, ocr,"
            " page_image, possibly_stale, tsv, embedding, fingerprint, extractor_version)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            " to_tsvector('simple', %s), %s, %s, %s)", rows)
        passage_alts = []
        for pid, alts in ds.passage_access.items():
            passage_alts += _alternatives_rows("passage", pid, alts)

        cur.executemany(
            f"INSERT INTO {s}.assets (asset_id, model, serial, site, site_name, customer, region,"
            " install_date, firmware, oil_type, contract_end) VALUES"
            " (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(a.asset_id, a.model, a.serial, a.site, a.site_name, a.customer, a.region,
              a.install_date, a.firmware, a.oil_type, a.contract_end)
             for a in ds.assets.values()])
        cur.executemany(f"INSERT INTO {s}.asset_aliases (alias, asset_id, source) VALUES"
                        " (%s,%s,%s)",
                        [(alias, aid, src) for alias, (aid, src) in ds.asset_aliases.items()])
        cur.executemany(f"INSERT INTO {s}.site_aliases (alias, site) VALUES (%s,%s)",
                        list(ds.site_aliases.items()))
        cur.executemany(
            f"INSERT INTO {s}.service_events (event_id, asset_id, event_date, event_type,"
            " fault_code, status, notes_original, notes_en, parts, labor_hours, run_hours,"
            " technician, sources, passage_id) VALUES"
            " (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(e.event_id, e.asset_id, e.event_date, e.event_type, e.fault_code, e.status,
              e.notes_original, e.notes_en, e.parts, e.labor_hours, e.run_hours, e.technician,
              Jsonb(e.sources), e.passage_id) for e in ds.events])
        event_alts = []
        for e in ds.events:
            uniq = sorted({tuple(sorted(a)) for a in e.required_groups})
            event_alts += _alternatives_rows("event", e.event_id, [list(a) for a in uniq])

        cur.executemany(
            f"INSERT INTO {s}.document_relations (from_doc, to_doc, relation, quote, page)"
            " VALUES (%s,%s,%s,%s,%s)",
            [(r.from_doc, r.to_doc, r.relation, r.quote, r.page) for r in ds.relations])
        cur.executemany(
            f"INSERT INTO {s}.bulletin_rules (rule_id, doc_id, model, serial_from, serial_to,"
            " firmware_condition, market_condition, variant_condition, outcome, campaign_code,"
            " action_summary, quote, page) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(r.rule_id, r.doc_id, r.model, r.serial_from, r.serial_to, r.firmware_condition,
              r.market_condition, r.variant_condition, r.outcome, r.campaign_code,
              r.action_summary, r.quote, r.page) for r in ds.bulletin_rules])
        cur.executemany(
            f"INSERT INTO {s}.bulletin_assets (doc_id, asset_id, status, rule_id, reason)"
            " VALUES (%s,%s,%s,%s,%s)",
            [(b.doc_id, b.asset_id, b.status, b.rule_id, b.reason) for b in ds.bulletin_assets])
        cur.executemany(
            f"INSERT INTO {s}.access_alternatives (object_type, object_id, alt_no,"
            " required_groups) VALUES (%s,%s,%s,%s)", doc_alts + passage_alts + event_alts)
    return {"documents": len(ds.documents), "passages": len(ds.passages),
            "events": len(ds.events), "assets": len(ds.assets),
            "relations": len(ds.relations), "bulletin_rules": len(ds.bulletin_rules),
            "bulletin_assets": len(ds.bulletin_assets),
            "embedded": sum(1 for p in ds.passages if p in embeddings),
            "access_alternatives": len(doc_alts) + len(passage_alts) + len(event_alts)}
