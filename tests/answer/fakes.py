"""In-memory `Serving` and a scripted model for offline engine tests."""
import json
import re
from dataclasses import dataclass, field

from copilot_answer.llm import FakeLLM
from copilot_answer.serving import (
    Asset,
    BulletinStatus,
    DatasetInfo,
    Document,
    Event,
    Passage,
    ProcedureAlt,
    Relation,
)
from copilot_answer.validate import ident_norm
from copilot_contracts import Identity
from copilot_ingest.settings import get_settings

HV_MARKERS = ("1,000 V DC", "100 MOHM", "50 V DC", "P9.01", "TP1", "TP2")
NA_TECH = frozenset({"region-na", "family-compressors", "family-pumps"})
HV_TECH = NA_TECH | {"cert-hv"}


def _has_id(key: str, haystack: str) -> bool:
    """Whole identifier match, like the identifier arrays in the database."""
    return re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![0-9])", haystack) is not None


def identity(user_id: str, groups: frozenset[str]) -> Identity:
    return Identity(user_id=user_id, name=user_id, groups=groups)


@dataclass
class FakeServing:
    docs: dict[str, Document] = field(default_factory=dict)
    doc_groups: dict[str, frozenset[str]] = field(default_factory=dict)
    corpus: dict[str, Passage] = field(default_factory=dict)
    fleet: list[Asset] = field(default_factory=list)
    statuses: list[BulletinStatus] = field(default_factory=list)
    procs: list[ProcedureAlt] = field(default_factory=list)
    rels: list[Relation] = field(default_factory=list)
    markers: dict[str, tuple[str, ...]] = field(default_factory=dict)
    hidden_distance: float = 0.3
    """Distance of every hidden passage to any question (the fake has no real embeddings)."""
    version: str = "ds_9001"

    def add_doc(self, doc: Document, groups: frozenset[str], *passages: Passage) -> None:
        self.docs[doc.doc_id] = doc
        self.doc_groups[doc.doc_id] = groups
        for p in passages:
            self.corpus[p.passage_id] = p

    def _visible(self, groups: frozenset[str]) -> list[Passage]:
        return [p for p in self.corpus.values() if self.doc_groups[p.doc_id] <= groups]

    def dataset_info(self) -> DatasetInfo:
        s = get_settings()
        return DatasetInfo(self.version, s.embedding_model, s.embedding_dims)

    def restricted_procedures(self) -> list[ProcedureAlt]:
        return self.procs

    def assets(self) -> list[Asset]:
        return self.fleet

    def asset_aliases(self) -> dict[str, str]:
        return {}

    def site_aliases(self) -> dict[str, str]:
        return {}

    def relations(self) -> list[Relation]:
        return self.rels

    def bulletin_statuses(self, asset_id: str) -> list[BulletinStatus]:
        return [b for b in self.statuses if b.asset_id == asset_id]

    def documents(self, groups):
        return {d: doc for d, doc in self.docs.items() if self.doc_groups[d] <= groups}

    def passages(self, groups, ids):
        vis = {p.passage_id: p for p in self._visible(groups)}
        return {i: vis[i] for i in ids if i in vis}

    def doc_passages(self, groups, doc_id):
        return [p for p in self._visible(groups) if p.doc_id == doc_id]

    def identifier_search(self, groups, ids, k):
        keys = [ident_norm(i) for i in ids]
        def hay(p: Passage) -> str:
            return ident_norm(" ".join([p.all_text, *p.models, *self.docs[p.doc_id].models]))
        return [p.passage_id for p in self._visible(groups)
                if any(_has_id(key, hay(p)) for key in keys)][:k]

    def keyword_search(self, groups, query, k):
        terms = [t.strip().casefold() for t in query.split(" OR ") if t.strip()]
        return [p.passage_id for p in self._visible(groups)
                if any(t in p.all_text.casefold() for t in terms)][:k]

    def vector_search(self, groups, embedding, k):
        return [p.passage_id for p in self._visible(groups)][:k]

    def visible_passages(self, groups, ids):
        vis = {p.passage_id for p in self._visible(groups)}
        return {i for i in ids if i in vis}

    def events(self, groups, asset_id) -> list[Event]:
        return []

    def restricted_markers(self):
        return self.markers

    def hidden_exists(self, groups, ids, embedding, max_distance):
        keys = [ident_norm(i) for i in ids]
        hidden = [p for p in self.corpus.values() if not self.doc_groups[p.doc_id] <= groups]
        close = max_distance is None or self.hidden_distance <= max_distance
        return close and any(
            _has_id(key, ident_norm(" ".join([p.all_text, *self.docs[p.doc_id].models])))
            for p in hidden for key in keys)


def corpus() -> FakeServing:
    s = FakeServing()
    s.fleet = [
        Asset("TAC-C-0143", "VRS-110", "VRS110-220311", "TAC", "Tacoma Plant", "NA", "5.0"),
        Asset("FRS-P-0012", "HCP-350", "HCP350-230100", "FRS", "Fresno Bottling Plant", "NA"),
        Asset("FRS-P-0031", "HCP-350", "HCP350-241187", "FRS", "Fresno Bottling Plant", "NA"),
    ]
    s.add_doc(Document("d_vrs", "Vastra VRS-110 Service Manual", "service_manual", 3,
                       ("VRS-110",)), frozenset({"family-compressors"}),
              Passage("p_vrs1", "d_vrs", "E-31 is a VFD overcurrent fault. The operator panel "
                      "reset is disabled; the reset is done under HV-PROC-07 by an HV-certified "
                      "technician. Others record the event log and raise a work order.",
                      heading_path=["7 Variable speed drive"], anchor={"page": 41}))
    s.add_doc(Document("d_hv7", "HV-PROC-07 VRS-110 VFD Fault Reset", "controlled_procedure", 1,
                       ("VRS-110",)), frozenset({"cert-hv", "family-compressors"}),
              Passage("p_hv7", "d_hv7", "Test insulation at 1,000 V DC; it must be above 100 MOhm."
                      " Prove the DC bus below 50 V DC at TP1 and TP2. Set P9.01 to 1.",
                      heading_path=["6. Procedure"], restricted_tags=["HV-PROC-07"]))
    s.add_doc(Document("d_iom", "Halden HCP-350 IOM Rev D", "service_manual", 3, ("HCP-350",),
                       "D"), frozenset({"family-pumps"}),
              Passage("p_iom", "d_iom", "Tighten the casing bolts to 45 N-m in a cross pattern.",
                      heading_path=["8.4 Replacing the mechanical seal"], anchor={"page": 7}))
    s.add_doc(Document("d_sb9", "Halden SB-2025-009", "bulletin", 2, ("HCP-350",)),
              frozenset({"family-pumps"}),
              Passage("p_sb9", "d_sb9", "For HCP-350 serials HCP350-240001 and later, tighten "
                      "the casing bolts to 38 N-m. 45 N-m applies only to earlier serials.",
                      heading_path=["5 Corrective action"], anchor={"page": 2}))
    s.add_doc(Document("d_500", "Halden HCP-500 IOM Rev B", "service_manual", 3, ("HCP-500",)),
              frozenset({"family-pumps"}),
              Passage("p_500", "d_500", "Casing bolts: 60 N-m. Clean the strainer above 0.30 bar.",
                      heading_path=["8.4"], anchor={"page": 8}))
    s.add_doc(Document("d_200", "Halden HCP-200 IOM", "service_manual", 3, ("HCP-200",)),
              frozenset({"family-pumps"}),
              Passage("p_200", "d_200", "Impeller-to-casing clearance: 0.38–0.50 mm diametral.",
                      heading_path=["Table 3.1"], anchor={"page": 5}))
    s.statuses = [
        BulletinStatus("d_sb9", "FRS-P-0031", "affected", "r1", "serial in range",
                       quote="tighten the casing bolts to 38 N-m", page=2),
        BulletinStatus("d_sb9", "FRS-P-0012", "not_affected", "r1", "serial below range"),
    ]
    s.markers = {"HV-PROC-07": HV_MARKERS}
    s.procs = [ProcedureAlt("HV-PROC-07", "HV-PROC-07 VRS-110 VFD Fault Reset", "d_hv7",
                            frozenset({"cert-hv", "family-compressors"}))]
    return s


def label(prompt: str, passage_text_start: str) -> str:
    """Label (P1, P2...) the engine gave the passage starting with `passage_text_start`."""
    blocks = re.split(r"\n(?=\[P\d+\])", prompt)
    for b in blocks:
        if passage_text_start in b:
            return re.match(r"\[(P\d+)\]", b.strip()).group(1)
    raise AssertionError(f"passage not offered: {passage_text_start!r}")


def scripted(generate, sufficiency=None, regenerate=None, followup=None,
             complete=None) -> FakeLLM:
    """A model whose replies are produced by functions of the prompt. The completeness pass
    adds nothing unless `complete` is given."""
    def handler(version: str, prompt: str) -> dict:
        if version.startswith("answer-sufficiency"):
            return (sufficiency(prompt) if sufficiency else
                    {"covered": True, "out_of_scope": False, "restricted_procedure": None,
                     "reason": "covered"})
        if version.startswith("answer-generate"):
            out = generate(prompt)
            out.setdefault("conflicts", [])
            out.setdefault("work_order", {"needed": False, "summary": "", "fault_code": None,
                                          "parts": [], "cites": []})
            return out
        if version.startswith("answer-followup"):
            return followup(prompt)
        if version.startswith("answer-regenerate"):
            return regenerate(prompt) if regenerate else {"fixes": []}
        if version.startswith("answer-complete"):
            return complete(prompt) if complete else {"additions": []}
        raise AssertionError(version)
    return FakeLLM(handler)


def sentence(text: str, *cites: str, kind: str = "statement", step: int | None = None) -> dict:
    return {"kind": kind, "step_number": step, "text": text, "cites": list(cites)}


def dump(resp) -> str:
    return json.dumps(json.loads(resp.model_dump_json()))
