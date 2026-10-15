"""Run order: register -> extract -> documents -> chunk -> history -> restricted -> access ->
embed -> index -> validate -> report -> publish.

Expensive work (extraction, OCR, model calls, embeddings) is cached by content fingerprint and
stage version, so a rerun only redoes what changed. Cheap deterministic stages are recomputed.
"""
import hashlib
import traceback
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from copilot_ingest import review as review_q
from copilot_ingest.acl import AccessRules, load_access_rules
from copilot_ingest.db.repo import connect, create_dataset_version, published_version
from copilot_ingest.ids import doc_id_for
from copilot_ingest.models import (
    Anchor,
    Document,
    ExtractResult,
    Passage,
    QuarantineRecord,
    Relation,
    ReviewItem,
)
from copilot_ingest.providers.base import ProviderUnavailable
from copilot_ingest.providers.cache import get_provider
from copilot_ingest.settings import get_settings
from copilot_ingest.stages import classify, enrich, restricted, scan, translate
from copilot_ingest.stages.chunk import chunk, detect_lang
from copilot_ingest.stages.extract import extract_file, tabular_source_for
from copilot_ingest.stages.index import Dataset, compute_access, write
from copilot_ingest.stages.link import build_history, event_text
from copilot_ingest.stages.normalize import identifiers
from copilot_ingest.stages.publish import PublishRefused, prune, publish
from copilot_ingest.stages.register import register
from copilot_ingest.stages.report import write_report
from copilot_ingest.stages.validate import Context, passed, validate

EXIT_PUBLISHED, EXIT_ERROR, EXIT_VALIDATION_FAILED, EXIT_BUILT = 0, 1, 2, 3


@dataclass
class RunOptions:
    corpus: Path | None = None
    acl: Path | None = None
    users: Path | None = None
    only: set[str] | None = None  # re-extract these files; the rest reuse cached extraction
    from_stage: str | None = None  # "extract": re-extract every file (or every --only file)
    publish: bool = True
    offline: bool = False
    embed: bool = True


@dataclass
class RunState:
    run_id: str
    rules: AccessRules
    extracts: dict[str, ExtractResult] = field(default_factory=dict)
    quarantine: list[QuarantineRecord] = field(default_factory=list)
    review: list[ReviewItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    file_detail: dict[str, dict] = field(default_factory=dict)
    decisions: review_q.Decisions = field(default_factory=review_q.Decisions)


def _run_id() -> str:
    """UTC timestamp to the second, e.g. 20261014T212300Z."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


# --- stages ---------------------------------------------------------------------------------

def _extract_all(state: RunState, corpus: Path, files, force: Callable[[str], bool]) -> None:
    """Extract each file, reusing the cache unless `force` says otherwise. A file that fails is
    quarantined as unreadable instead of failing the run."""
    for sf in files:
        try:
            result, cached = extract_file(corpus / sf.path, sf.path, sf.fingerprint,
                                          force=force(sf.path))
        except Exception as e:  # noqa: BLE001
            state.quarantine.append(QuarantineRecord(path=sf.path, stage="extract",
                                                     reason="unreadable",
                                                     detail=f"{type(e).__name__}: {e}"))
            state.errors.append(f"{sf.path}: {traceback.format_exc(limit=2)}")
            continue
        state.extracts[sf.path] = result
        cov = Counter(p.status for p in result.pages)
        state.file_detail[sf.path] = {"extractor": result.extractor, "cached": cached,
                                      "coverage": dict(cov)}


def _scan(state: RunState, corpus: Path, provider, settings) -> dict:
    """OCR for scanned pages; reads are cached, the value cross-check reruns every build."""
    fleet = _known_models(state)
    out: dict = {}
    for path, r in list(state.extracts.items()):
        if r.extractor != "pdf" or not any(p.status == "scanned" for p in r.pages):
            continue
        try:
            read = scan.read_pages(corpus / path, r, settings.data_dir, provider,
                                   settings.vision_model)
        except Exception as e:  # noqa: BLE001
            state.errors.append(f"{path}: OCR failed: {e}")
            read = None
        if read is None:
            out[path] = {"status": "OCR not run; pages stay scanned"}
            continue
        checked = scan.apply(r, read, fleet, state.decisions)
        state.extracts[path] = checked.result
        state.review += checked.review
        out[path] = checked.stats
    return out


def _full_text(r: ExtractResult) -> str:
    """Block text joined by newlines; empty if the extract has no blocks."""
    if r.blocks:
        return "\n".join(b.text for b in r.blocks)
    return ""


def _known_models(state: RunState) -> set[str]:
    """Machine models in the fleet register; empty if the register was not extracted."""
    fleet = state.extracts.get("data/fleet_register.csv")
    return {rec["model"] for rec in fleet.records} if fleet else set()


def _build_documents(state: RunState, ds: Dataset, sources: dict) -> dict[str, ExtractResult]:
    """Group extracts into documents (identical content -> one document, several origins)."""
    primary: dict[str, ExtractResult] = {}
    known = _known_models(state)
    for path, r in sorted(state.extracts.items()):
        text = _full_text(r)
        doc_id = doc_id_for(text) if text.strip() else doc_id_for(f"fingerprint:{r.fingerprint}")
        sf = sources[path]
        origin = {"path": path, "fingerprint": r.fingerprint,
                  "source_system": sf.source_system or "unknown",
                  "required_groups": sorted(sf.required_groups or [])}
        if doc_id in ds.documents:
            ds.documents[doc_id].origins.append(origin)
            continue
        title = state.rules.titles.get(path) or r.title
        doc_type = classify.doc_type_for(path, r.title, sf.source_system)
        props = classify.document_properties(r)
        models = [m for m in identifiers(f"{Path(path).name} {title or ''} {r.title or ''}")
                  ["models"] if not known or m in known]
        missing = [p.page for p in r.pages if p.status in ("scanned", "unrecoverable")]
        truncated = r.flags.get("truncated_pages", [])
        ds.documents[doc_id] = Document(
            doc_id=doc_id, title=title, doc_type=doc_type,
            authority_tier=classify.authority_tier(doc_type),
            controlled=classify.is_controlled(doc_type), models=models,
            revision=props["revision"], issue_date=props["issue_date"],
            status="partial" if missing or truncated else "active",
            missing_pages=sorted(set(missing) | set(truncated)),
            extractor_version=r.extractor_version, origins=[origin])
        primary[doc_id] = r
    return primary


def _metadata(state: RunState, ds: Dataset, primary: dict[str, ExtractResult], provider,
              settings) -> tuple[dict[str, enrich.Metadata], dict]:
    """Revision, issue date, canonical origin and supersession (US3)."""
    mds: dict[str, enrich.Metadata] = {}
    sources_used = Counter()
    for doc_id, r in primary.items():
        d = ds.documents[doc_id]
        d.origins.sort(key=lambda o: (classify.source_rank(o["source_system"]), o["path"]))
        d.title = state.rules.titles.get(d.origins[0]["path"]) or d.title
        md = enrich.rule_metadata(r, classify.document_properties(r))
        missing = [f for f in ("revision", "issue_date") if f not in md.fields]
        if missing and d.doc_type in enrich.NEEDS_METADATA:
            enrich.model_metadata(r, md, missing, provider, settings.llm_model_fast,
                                  d.origins[0]["path"], state.decisions)
        state.review += md.review
        if "revision" in md.fields:
            d.revision = str(md.fields["revision"].value)
        if "issue_date" in md.fields:
            d.issue_date = md.fields["issue_date"].value
        sources_used.update(ev.source for ev in md.fields.values())
        mds[doc_id] = md
    ds.relations += enrich.supersessions(ds.documents, mds)
    for rel in ds.relations:
        if rel.relation == "supersedes":
            ds.documents[rel.to_doc].status = "superseded"
    return mds, {"fields_by_source": dict(sources_used),
                 "unverified": sum(len(m.review) for m in mds.values()),
                 "superseded": [f"{ds.documents[r.from_doc].title} supersedes "
                                f"{ds.documents[r.to_doc].title}" for r in ds.relations
                                if r.relation == "supersedes"]}


def _bulletins(ds: Dataset, primary: dict[str, ExtractResult], provider, settings) -> dict:
    """Applicability rules for each bulletin and the resulting status of every fleet asset."""
    out = {}
    assets = list(ds.assets.values())
    for doc_id, r in primary.items():
        d = ds.documents[doc_id]
        if d.doc_type != "bulletin":
            continue
        rules = enrich.bulletin_rules(r, doc_id)
        conditions, notes = enrich.bulletin_conditions(r, rules, provider,
                                                       settings.llm_model_fast)
        rules += enrich.condition_rules(conditions, doc_id)
        statuses = enrich.evaluate(rules, assets, doc_id, partial=d.status == "partial")
        ds.bulletin_rules += rules
        ds.bulletin_assets += statuses
        out[d.title or doc_id] = {
            "rules": len(rules), "conditions": [c.quote for c in conditions], "notes": notes,
            "units": {s.asset_id: s.status for s in statuses}}
    return out


def _stale(ds: Dataset, embeddings: dict[str, list[float]]) -> dict:
    """Flag passages a newer document may contradict and relate the document pairs. Without
    embeddings the topic similarity check is skipped."""
    found = enrich.possibly_stale(ds.documents, ds.passages, embeddings)
    pairs = set()
    for s in found:
        ds.passages[s.passage_id].possibly_stale = True
        pairs.add((ds.passages[s.passage_id].doc_id, s.newer_doc))
    ds.relations += [Relation(from_doc=a, to_doc=b, relation="possibly_stale_vs")
                     for a, b in sorted(pairs)]
    return {"passages": [{"doc": ds.documents[ds.passages[s.passage_id].doc_id].title,
                          "heading": " > ".join(ds.passages[s.passage_id].heading_path),
                          "newer": ds.documents[s.newer_doc].title,
                          "topic_similarity": round(s.score, 3) if s.score is not None else None}
                         for s in found],
            "pairs": [f"{ds.documents[a].title} vs {ds.documents[b].title}"
                      for a, b in sorted(pairs)],
            "topic_check": "embeddings" if embeddings else "skipped (no embeddings)"}


def _translate(ds: Dataset, provider, settings) -> dict:
    """English text for service notes and non-English passages. Bilingual document passages
    are left as is; event passages get the note replaced by its translation."""
    lang_of = {p.passage_id: p.lang for p in ds.passages.values()}
    notes = [e.notes_original for e in ds.events if e.notes_original and (
        e.sources[0]["system"] == "servio" or lang_of.get(e.passage_id) not in ("en", None))]
    passages = [p for pid, p in ds.passages.items() if pid not in ds.event_passages
                and p.lang not in ("en", None)
                and ("record" in p.block_types or not translate.is_bilingual(p.text_original))]
    tr = translate.Translations.load()
    tr.translate(notes + [p.text_original for p in passages], provider,
                 settings.llm_model_fast, settings.llm_model_strong)
    events = {e.event_id: e for e in ds.events}
    for pid, eid in ds.event_passages.items():
        ev, p = events[eid], ds.passages[pid]
        t = tr.get(ev.notes_original or "")
        if t and t["en"].strip() != ev.notes_original.strip():
            ev.notes_en = t["en"]
            p.text_en = p.text_original.replace(ev.notes_original, t["en"], 1)
    for ev in ds.events:
        if ev.notes_en is None and (t := tr.get(ev.notes_original or "")) and \
                t["en"].strip() != (ev.notes_original or "").strip():
            ev.notes_en = t["en"]
    for p in passages:
        if t := tr.get(p.text_original):
            p.text_en = t["en"]
    bilingual = sum(1 for pid, p in ds.passages.items() if pid not in ds.event_passages
                    and p.lang not in ("en", None) and p not in passages)
    return {"notes_considered": len(set(notes)), "passages_translated": sum(
                1 for p in passages if p.text_en),
            "events_with_notes_en": sum(1 for e in ds.events if e.notes_en),
            "bilingual_passages_not_translated": bilingual, **dict(tr.stats)}


def _default_lang(path: str) -> str | None:
    """Servio exports are Dutch; other sources have no default language."""
    source = tabular_source_for(path)
    return "nl" if source == "servio" else None


def _chunk_all(ds: Dataset, primary: dict[str, ExtractResult]) -> None:
    """Passages for each non-tabular document (tabular rows become passages in `_history`),
    with OCR status and page image on OCR'd pages, and the document's languages."""
    for doc_id, r in primary.items():
        if r.extractor == "tabular":
            continue
        langs = Counter()
        ocr_images = r.flags.get("ocr_images", {})
        for p in chunk(r, doc_id, _default_lang(r.path)):
            if str(p.anchor.page) in ocr_images:
                p.ocr = "has_withheld_values" if "[[unverified:" in p.text_original \
                    else "verified"
                p.page_image = ocr_images[str(p.anchor.page)]
            ds.passages[p.passage_id] = p
            if p.lang:
                langs[p.lang] += 1
        ds.documents[doc_id].languages = sorted(langs)


def _history(state: RunState, ds: Dataset, doc_by_path: dict[str, str], sources: dict) -> dict:
    """Assets and service events from the fleet register, maintenance exports and cases. Each
    maintenance event gets its own passage; case events point at the case record's passage."""
    ex = state.extracts

    def req(path):
        """Sorted required groups of a source file."""
        return sorted(sources[path].required_groups or [])

    maintenance = [(tabular_source_for(p), ex[p], req(p)) for p in ex
                   if tabular_source_for(p) in ("maintpro", "servio")]
    cases = [(ex[p], req(p)) for p in ex if ex[p].extractor == "salesforce"]
    h = build_history(ex.get("data/fleet_register.csv"), maintenance, cases, state.decisions)
    state.review += h.review
    state.errors += h.errors
    ds.assets, ds.asset_aliases, ds.site_aliases = h.assets, h.asset_aliases, h.site_aliases

    case_passages = {p.anchor.record_id: p.passage_id for p in ds.passages.values()
                     if p.anchor.record_id and "record" in p.block_types}
    for ev in h.events:
        src = ev.sources[0]
        if src["system"] == "salesforce":
            ev.passage_id = case_passages.get(src["record_id"])
            continue
        path = src["path"]
        doc_id = doc_by_path[path]
        text = event_text(ev)
        ids = identifiers(text)
        p = Passage(
            passage_id="p_ev_" + ev.event_id[2:], doc_id=doc_id,
            anchor=Anchor(record_id=src["record_id"]), block_types=["record"],
            lang=detect_lang(ev.notes_original or "") or src.get("lang"), text_original=text,
            fault_codes=sorted(set(ids["fault_codes"]) | ({ev.fault_code} if ev.fault_code
                                                          else set())),
            part_numbers=ids["part_numbers"], asset_ids=sorted(set(ids["asset_ids"])
                                                               | {ev.asset_id}),
            serials=ids["serials"], case_numbers=ids["case_numbers"], models=ids["models"],
            fingerprint=state.extracts[path].fingerprint,
            extractor_version=state.extracts[path].extractor_version)
        ds.passages[p.passage_id] = p
        ds.event_passages[p.passage_id] = ev.event_id
        ev.passage_id = p.passage_id
    ds.events = h.events
    return {**h.counts, "events": len(h.events), "assets": len(h.assets),
            "asset_aliases": len(h.asset_aliases), "site_aliases": len(h.site_aliases),
            "maintenance rows merged with cases": h.merged_cases,
            "merged with differing access rules": h.merged_with_different_rules,
            "unresolved links": sum(1 for r in h.review if r.kind == "unresolved_link"),
            "unknown assets": sum(1 for r in h.review if r.kind == "unknown_asset")}


def _restricted(state: RunState, ds: Dataset, embed_steps) -> dict:
    """Tag passages of restricted procedures, using each document's strictest origin. If
    embedding fails, tagging reruns without the similarity check."""
    docs = {}
    for d in ds.documents.values():
        strictest = max(d.origins, key=lambda o: len(o["required_groups"]))
        docs[d.doc_id] = {"path": strictest["path"], "controlled": d.controlled,
                          "groups": strictest["required_groups"],
                          "name": (d.title or strictest["path"]).split()[0]}
    passages = list(ds.passages.values())
    procs = restricted.build_procedures(docs, passages, classify.certification_groups())
    state.review += restricted.propose_markers(procs, passages, state.decisions)
    paths = {d.doc_id: d.origins[0]["path"] for d in ds.documents.values()}
    try:
        result = restricted.tag(procs, passages, embed_steps, paths, state.decisions)
    except ProviderUnavailable:
        result = restricted.tag(procs, passages, None, paths, state.decisions)
    state.review += result.review
    return {"procedures": [{"name": p.name, "groups": p.groups, "markers": p.markers,
                            "proposed": p.proposed, "steps": len(p.steps)} for p in procs],
            "tagged": result.tagged, "released": result.released,
            "similarity_checked": result.similarity_checked}


def _embed(ds: Dataset, provider, settings) -> tuple[dict[str, list[float]], str]:
    """Passage vectors (heading path, English text, original text) and a report note; empty
    vectors if the provider is unavailable."""
    ids = list(ds.passages)
    texts = [" > ".join(p.heading_path) + "\n"
             + (f"{p.text_en}\n\n{p.text_original}" if p.text_en else p.text_original)
             for p in (ds.passages[i] for i in ids)]
    try:
        vectors = provider.embed(settings.embedding_model, texts, settings.embedding_dims)
    except ProviderUnavailable as e:
        return {}, f"skipped: {e}"
    return dict(zip(ids, vectors, strict=True)), f"{len(vectors)} passages embedded"


# --- run ------------------------------------------------------------------------------------

def run(opts: RunOptions) -> tuple[int, dict]:
    """One build; returns the exit code and report. The run is recorded and reported even if a
    stage fails. With embeddings off, every model call is cache-only too."""
    settings = get_settings()
    corpus = (opts.corpus or settings.corpus_dir).resolve()
    rules = load_access_rules(opts.acl or settings.acl_path, opts.users or settings.users_path)
    state = RunState(run_id=_run_id(), rules=rules)
    report: dict = {"run_id": state.run_id, "outcome": "error", "corpus": str(corpus)}
    provider = get_provider(offline=opts.offline or not opts.embed)
    report["provider"] = provider.name

    with connect() as conn:
        conn.execute("INSERT INTO control.runs (run_id) VALUES (%s)", (state.run_id,))
        conn.commit()
        try:
            code = _run(conn, opts, corpus, state, report, provider, settings)
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            if report.get("dataset_version") and conn.execute(
                    "SELECT to_regnamespace(%s)", (report["dataset_version"],)
            ).fetchone()[0] is None:
                report["dataset_version"] = None  # the rollback removed the unfinished version
            report["errors"] = state.errors + [f"{type(e).__name__}: {e}",
                                               traceback.format_exc()]
            code = EXIT_ERROR
        report_dir = settings.data_dir / "reports" / state.run_id
        path = write_report(report_dir, report)
        conn.execute("UPDATE control.runs SET finished_at = now(), dataset_version = %s,"
                     " outcome = %s, report_path = %s WHERE run_id = %s",
                     (report.get("dataset_version"), report["outcome"], str(path),
                      state.run_id))
        conn.commit()
    report["report_path"] = str(path)
    return code, report


def _run(conn, opts, corpus, state: RunState, report, provider, settings) -> int:
    """All stages in order, filling `report`; returns the exit code. Review items and file
    status are committed before validation, so they persist even if validation fails."""
    previous = dict(conn.execute("SELECT path, fingerprint FROM control.source_files"
                                 " WHERE status <> 'removed'").fetchall())
    reg = register(corpus, state.rules, previous)
    state.quarantine += reg.quarantine
    if opts.only and (unknown := sorted(opts.only - {f.path for f in reg.files})):
        raise ValueError(f"--only paths not in the corpus: {unknown}")
    _extract_all(state, corpus, reg.active, lambda path: (
        (opts.only is not None and path in opts.only)
        or (opts.from_stage == "extract" and (opts.only is None or path in opts.only))))
    state.decisions = review_q.load_decisions(conn, _fingerprints(state))
    report["ocr"] = _scan(state, corpus, provider, settings)
    sources = {f.path: f for f in reg.files}
    quarantined = {q.path: q.reason for q in state.quarantine}

    ds = Dataset()
    primary = _build_documents(state, ds, sources)
    _, report["metadata"] = _metadata(state, ds, primary, provider, settings)
    doc_by_path = {o["path"]: d.doc_id for d in ds.documents.values() for o in d.origins}
    _chunk_all(ds, primary)
    report["history"] = _history(state, ds, doc_by_path, sources)
    report["bulletins"] = _bulletins(ds, primary, provider, settings)
    report["translation"] = _translate(ds, provider, settings)

    embeddings: dict[str, list[float]] = {}
    embed_note = "skipped: disabled"
    if opts.embed:
        embeddings, embed_note = _embed(ds, provider, settings)
    embed_steps = None
    if embeddings:
        def embed_steps(texts):
            """Embed texts with the run's embedding model."""
            return provider.embed(settings.embedding_model, texts, settings.embedding_dims)
    report["restricted"] = _restricted(state, ds, embed_steps)
    report["stale"] = _stale(ds, embeddings)
    compute_access(ds)

    schema = create_dataset_version(conn)
    report["dataset_version"] = schema
    counts = write(conn, schema, ds, embeddings)
    conn.execute(f"INSERT INTO {schema}.dataset_info (embedding_model, embedding_dims)"
                 " VALUES (%s, %s)", (settings.embedding_model if embeddings else None,
                                      settings.embedding_dims if embeddings else None))
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO {schema}.restricted_markers (procedure, marker, status)"
            " VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            [(p["name"], m, status) for p in report["restricted"]["procedures"]
             for status, key in (("approved", "markers"), ("proposed", "proposed"))
             for m in p[key]])
    counts["embeddings"] = embed_note
    report["changes"] = _changes(conn, reg, ds)

    review_q.upsert_items(conn, [_with_ids(i, state) for i in state.review], state.run_id)
    review_q.close_unraised(conn, state.run_id)
    report["decisions_applied"] = sorted(set(state.decisions.applied))
    _record_files(conn, state, reg)
    conn.commit()

    keys = ("item_id", "kind", "path", "field", "reason", "candidates")
    rows = conn.execute(f"SELECT {', '.join(keys)} FROM control.review_items"  # noqa: S608
                        " WHERE status = 'open' AND last_run = %s ORDER BY kind, path",
                        (state.run_id,))
    open_items = [dict(zip(keys, r, strict=True)) for r in rows]
    ctx = Context(conn=conn, schema=schema, ds=ds, rules=state.rules, extracts=state.extracts,
                  quarantined=quarantined, open_review=open_items,
                  embeddings_expected=opts.embed and bool(embeddings))
    results = validate(ctx)
    conn.rollback()  # validation only reads; clear any failed statement
    ok = passed(results)

    passages_per_doc = Counter(p.doc_id for p in ds.passages.values())
    files = []
    for f in reg.files:
        if f.path in quarantined:
            q = next(q for q in state.quarantine if q.path == f.path)
            files.append({"path": f.path, "outcome": f"quarantined:{q.reason}",
                          "detail": q.detail})
            continue
        doc = ds.documents[doc_by_path[f.path]]
        is_dup = doc.origins[0]["path"] != f.path
        detail = state.file_detail.get(f.path, {})
        outcome = "duplicate" if is_dup else ("partial" if doc.status == "partial"
                                              else "ingested")
        note = f"same content as `{doc.origins[0]['path']}`" if is_dup else ""
        if doc.status == "partial" and not is_dup:
            r = state.extracts[f.path]
            parts = []
            for status, label in (("scanned", "scanned, OCR pending"),
                                  ("unrecoverable", "damaged, no text recoverable")):
                pages = [p.page for p in r.pages if p.status == status]
                if pages:
                    parts.append(f"pages {pages} {label}")
            if r.flags.get("truncated_pages"):
                parts.append(f"pages {r.flags['truncated_pages']} damaged, text cut off")
            note = "; ".join(parts)
        if detail.get("cached"):
            note = (note + "; " if note else "") + "unchanged, reused extraction"
        files.append({"path": f.path, "outcome": outcome, "detail": note,
                      "passages": passages_per_doc.get(doc.doc_id, 0) if not is_dup else 0})
    report.update({
        "files": files, "removed": reg.removed, "acl_without_file": reg.acl_without_file,
        "added": reg.added, "changed": reg.changed, "counts": counts,
        "validation": [r.__dict__ for r in results],
        "review": [{k: i[k] for k in ("item_id", "kind", "path", "field", "reason")}
                   for i in open_items],
        "errors": state.errors,
    })

    if not ok:
        report["outcome"] = "validation_failed"
        return EXIT_VALIDATION_FAILED
    if not opts.publish:
        report["outcome"] = "built"
        return EXIT_BUILT
    try:
        publish(conn, schema, state.run_id, ok)
    except PublishRefused as e:
        state.errors.append(str(e))
        report["outcome"] = "validation_failed"
        return EXIT_VALIDATION_FAILED
    report["outcome"] = "published"
    report["pruned"] = prune(conn)
    return EXIT_PUBLISHED


def _changes(conn, reg, ds: Dataset) -> dict:
    """File and passage changes against the version currently serving."""
    out = {"files_added": len(reg.added), "files_changed": len(reg.changed),
           "files_unchanged": sum(1 for f in reg.files if not f.changed),
           "files_removed": len(reg.removed)}
    previous = published_version(conn)
    if previous:
        before = dict(conn.execute(f"SELECT passage_id, md5(text_original)"  # noqa: S608
                                   f" FROM {previous}.passages").fetchall())
        now = {pid: hashlib.md5(p.text_original.encode()).hexdigest()  # noqa: S324
               for pid, p in ds.passages.items()}
        out.update({"compared_with": previous,
                    "passages_added": len(now.keys() - before.keys()),
                    "passages_removed": len(before.keys() - now.keys()),
                    "passages_changed": sum(1 for k in now.keys() & before.keys()
                                            if now[k] != before[k]),
                    "passages_unchanged": sum(1 for k in now.keys() & before.keys()
                                              if now[k] == before[k])})
    return out


def _with_ids(item: ReviewItem, state: RunState) -> ReviewItem:
    """Review item with its source fingerprint filled in, ready for a stable ID."""
    return review_q.with_fingerprint(item, _fingerprints(state))


def _fingerprints(state: RunState) -> dict[str, str]:
    """Content fingerprint of each extracted file, by path."""
    return {p: r.fingerprint for p, r in state.extracts.items()}


def _record_files(conn, state: RunState, reg) -> None:
    """Record this run's quarantines and each file's status; files gone from the corpus are
    marked removed."""
    for q in state.quarantine:
        conn.execute("INSERT INTO control.quarantine (path, run_id, stage, reason, detail)"
                     " VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                     (q.path, state.run_id, q.stage, q.reason, q.detail))
    quarantined = {q.path for q in state.quarantine}
    for f in reg.files:
        status = "quarantined" if f.path in quarantined else f.status
        conn.execute(
            "INSERT INTO control.source_files (path, fingerprint, size_bytes, source_system,"
            " required_groups, status, first_seen_run, last_seen_run)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (path) DO UPDATE SET"
            " fingerprint = EXCLUDED.fingerprint, size_bytes = EXCLUDED.size_bytes,"
            " source_system = EXCLUDED.source_system, required_groups ="
            " EXCLUDED.required_groups, status = EXCLUDED.status, last_seen_run ="
            " EXCLUDED.last_seen_run",
            (f.path, f.fingerprint, f.size_bytes, f.source_system, f.required_groups, status,
             state.run_id, state.run_id))
    for path in reg.removed:
        conn.execute("UPDATE control.source_files SET status = 'removed', last_seen_run = %s"
                     " WHERE path = %s", (state.run_id, path))
