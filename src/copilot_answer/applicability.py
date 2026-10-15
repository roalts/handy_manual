"""Applicability decided by code over passage metadata (Principle IV, FR-008..011, research R4)."""
from dataclasses import dataclass, field

from copilot_answer.serving import Asset, Document, Passage, Relation

RECORD_TYPES = {"case_export", "maintenance_export"}


@dataclass
class Candidate:
    passage: Passage
    doc: Document
    score: float = 0.0
    superseded: bool = False
    stale: bool = False
    other_unit: bool = False
    bulletin_status: str | None = None
    labels: list[str] = field(default_factory=list)

    @property
    def pid(self) -> str:
        """Passage ID."""
        return self.passage.passage_id


@dataclass
class Filtered:
    evidence: list[Candidate]
    superseded: list[Candidate]
    stale: list[Candidate]
    dropped_model: list[Candidate]


def effective_models(p: Passage, doc: Document,
                     asset_models: dict[str, str] | None = None) -> set[str]:
    """Passage models, else document models; a record about named units gets their models."""
    eff = set(p.models) or set(doc.models)
    if not eff and doc.doc_type in RECORD_TYPES and asset_models:
        eff = {asset_models[a] for a in p.asset_ids if a in asset_models}
    return eff


def model_applies(p: Passage, doc: Document, models: list[str],
                  asset_models: dict[str, str] | None = None) -> bool:
    """A passage for a different model is never evidence; model-less passages are general."""
    if not models:
        return True
    eff = effective_models(p, doc, asset_models)
    return not eff or bool(eff & set(models))


def apply(cands: list[Candidate], models: list[str], asset: Asset | None,
          relations: list[Relation], visible_docs: set[str],
          bulletin_status: dict[str, str],
          asset_models: dict[str, str] | None = None) -> Filtered:
    """Drop other-model passages; set aside superseded ones unless the newer revision is hidden
    and stale ones when the newer source is visible; label the rest for the prompt."""
    superseded_by = {r.to_doc: r.from_doc for r in relations if r.relation == "supersedes"}
    stale_vs = {r.from_doc: r.to_doc for r in relations if r.relation == "possibly_stale_vs"}
    out = Filtered([], [], [], [])
    for c in cands:
        p, d = c.passage, c.doc
        if not model_applies(p, d, models, asset_models):
            out.dropped_model.append(c)
            continue
        if d.status == "superseded" or d.doc_id in superseded_by:
            c.superseded = True
            c.labels.append("SUPERSEDED revision")
            newer = superseded_by.get(d.doc_id)
            if newer is None or newer in visible_docs:
                out.superseded.append(c)
                continue
        if p.possibly_stale or d.doc_id in stale_vs:
            c.stale = True
            c.labels.append("POSSIBLY STALE")
            newer = stale_vs.get(d.doc_id)
            if newer is not None and newer in visible_docs:
                out.stale.append(c)
                continue
        if d.doc_type in RECORD_TYPES and p.asset_ids:
            if asset and asset.asset_id in p.asset_ids:
                c.labels.append(f"record for this unit ({asset.asset_id})")
            elif asset:
                c.other_unit = True
                c.labels.append(f"record for another unit ({', '.join(p.asset_ids)})")
            else:
                c.labels.append(f"record for unit {', '.join(p.asset_ids)}")
        if d.doc_id in bulletin_status:
            c.bulletin_status = bulletin_status[d.doc_id]
            c.labels.append(f"bulletin status for {asset.asset_id if asset else 'this unit'}: "
                            f"{c.bulletin_status} (decided by the fleet records)")
        out.evidence.append(c)
    return out
