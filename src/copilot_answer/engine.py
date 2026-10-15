"""The answer pipeline (Principle VIII): identify user, resolve asset, retrieve, filter
applicability, check sufficiency, generate, validate citations."""
import math
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from copilot_answer import build, complete, config, didyoumean, prompts
from copilot_answer.applicability import RECORD_TYPES, Candidate, apply, effective_models
from copilot_answer.ids import ASSET, PROCEDURE, Recognized, canonical_procedure, recognize
from copilot_answer.llm import LLM, Meter
from copilot_answer.resolve import Fleet, Resolution, candidates_differ, resolve
from copilot_answer.restricted import Unsatisfied, covering, guard, names_in, terms, unsatisfied
from copilot_answer.retrieve import consolidate, retrieve
from copilot_answer.serving import Asset, BulletinStatus, Document, Serving
from copilot_answer.validate import check_sentence, norm, strip_labels
from copilot_contracts import (
    AnswerResponse,
    AskRequest,
    AssetBulletin,
    Clarification,
    ClarifyOption,
    Identity,
    Notice,
    ResolvedAsset,
    Restricted,
    Sentence,
    WorkOrderSuggestion,
)
from copilot_ingest.settings import get_settings

HISTORY = re.compile(r"\b(before|history|previous(ly)?|again|last time|in the past|happened|"
                     r"recurr\w*|repeat\w*|what fixed)\b", re.I)
APPLYING = build.APPLYING
CONTROLLED = {"controlled_procedure", "work_instruction"}


def _supplied(labels: dict[str, Candidate]) -> dict[str, str]:
    """Text a cite grounds: the passage, plus its document title (a procedure's own name)."""
    return {lab: f"{c.doc.title}\n{c.passage.all_text}" for lab, c in labels.items()}


def _without_labels(gen: dict) -> dict:
    """Generated output with evidence labels removed from every text a technician reads."""
    out = dict(gen)
    out["sentences"] = [{**s, "text": strip_labels(s.get("text", ""))}
                        for s in gen.get("sentences", [])]
    out["conflicts"] = [{**x, "topic": strip_labels(x.get("topic", "")),
                         "sides": [{**side, "statement": strip_labels(side.get("statement", ""))}
                                   for side in x.get("sides", [])]}
                        for x in gen.get("conflicts", [])]
    if isinstance(gen.get("work_order"), dict):
        wo = gen["work_order"]
        out["work_order"] = {**wo, "summary": strip_labels(wo.get("summary") or "")}
    return out


def _distance(a: list[float], b: list[float]) -> float:
    """Cosine distance, as pgvector's `<=>`."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 1.0 - dot / (na * nb) if na and nb else 1.0


class ConfigurationError(RuntimeError):
    """The published dataset does not match the engine's embedding settings."""


@dataclass
class Timer:
    marks: dict[str, int] = field(default_factory=dict)
    start: float = field(default_factory=time.monotonic)
    last: float = field(default_factory=time.monotonic)

    def lap(self, name: str) -> None:
        """Add the milliseconds since the last mark to stage `name`."""
        now = time.monotonic()
        self.marks[name] = self.marks.get(name, 0) + int((now - self.last) * 1000)
        self.last = now

    def done(self) -> dict[str, int]:
        """Stage timings in ms, with the total since start."""
        self.marks["total"] = int((time.monotonic() - self.start) * 1000)
        return self.marks


@dataclass
class Context:
    identity: Identity
    request: AskRequest
    dataset_version: str
    meter: Meter
    timer: Timer
    res: Resolution | None = None
    docs: dict[str, Document] = field(default_factory=dict)
    statuses: list[BulletinStatus] = field(default_factory=list)
    bulletin_cites: dict[str, Candidate] = field(default_factory=dict)
    bulletin_docs: dict[str, list] = field(default_factory=dict)
    markers: dict[str, tuple[str, ...]] = field(default_factory=dict)
    embedding: list[float] | None = None
    question_used: str | None = None

    @property
    def groups(self) -> frozenset[str]:
        """The user's permission groups."""
        return self.identity.groups

    @property
    def scope(self) -> str:
        """Cache scope: dataset version and the exact group set."""
        return self.dataset_version + "|" + ",".join(sorted(self.groups))

    @property
    def asset(self) -> Asset | None:
        """The resolved machine, if any."""
        return self.res.asset if self.res else None


class Engine:
    """`copilot_contracts.AnswerEngine` over the serving schema."""

    def __init__(self, serving: Serving, llm: LLM, model: str | None = None,
                 embedding_model: str | None = None, embedding_dims: int | None = None) -> None:
        """Defaults from settings; loads the dataset (`ConfigurationError` on a mismatch)."""
        s = get_settings()
        self.serving = serving
        self.llm = llm
        self.model = model or s.llm_model_fast
        self.embedding_model = embedding_model or s.embedding_model
        self.embedding_dims = embedding_dims or s.embedding_dims
        self._version: str | None = None
        self._load()

    def _load(self) -> None:
        """Fail on an embedding mismatch; reload fleet, relations and restricted procedures when
        the serving dataset version changed."""
        info = self.serving.dataset_info()
        if (info.embedding_model, info.embedding_dims) != (self.embedding_model,
                                                           self.embedding_dims):
            raise ConfigurationError(
                f"dataset {info.dataset_version} uses {info.embedding_model}/"
                f"{info.embedding_dims}, engine is set to {self.embedding_model}/"
                f"{self.embedding_dims}")
        if info.dataset_version == self._version:
            return
        self._version = info.dataset_version
        self.fleet = Fleet({a.asset_id: a for a in self.serving.assets()},
                           self.serving.asset_aliases(), self.serving.site_aliases())
        self.relations = self.serving.relations()
        self.procedures = self.serving.restricted_procedures()
        self.cert_groups = {name: sorted(g for alt in self.procedures if alt.name == name
                                         for g in alt.required_groups if g.startswith("cert-"))
                            for name in {p.name for p in self.procedures}}

    # ------------------------------------------------------------------ pipeline

    def answer(self, identity: Identity, request: AskRequest) -> AnswerResponse:
        """Answer for the user (a follow-up is first made standalone); keeps the meter in
        `last_meter`."""
        self._load()
        ctx = Context(identity, request, self._version, Meter(), Timer())
        ctx.markers = self.serving.restricted_markers()
        self.last_meter = ctx.meter
        if request.previous:
            ctx.request = self._standalone(ctx, request)
            if ctx.request.question != request.question:
                ctx.question_used = ctx.request.question
            ctx.timer.lap("followup")
        resp = self._run(ctx)
        resp = resp.model_copy(update={"timings_ms": ctx.timer.done()})
        resp.check()
        return resp

    def _response(self, ctx: Context, status: str, **kw) -> AnswerResponse:
        """Build a response; labels are stripped from notices, and bulletin citations are added
        whenever a machine is resolved."""
        asset = kw.pop("asset") if "asset" in kw else self._resolved_asset(ctx)
        citations = dict(kw.pop("citations", {}))
        if kw.get("notices"):
            kw["notices"] = [n.model_copy(update={"text": strip_labels(n.text)}) if n.text else n
                             for n in kw["notices"]]
        if asset:
            for c in ctx.bulletin_cites.values():
                citations.setdefault(c.pid, build.citation(c))
        return AnswerResponse(answer_id="ans_" + uuid.uuid4().hex[:24],
                              dataset_version=ctx.dataset_version, status=status, asset=asset,
                              citations=citations, question_used=ctx.question_used, **kw)

    def _abstain(self, ctx: Context, reason: str, text: str) -> AnswerResponse:
        """Abstain with one notice (`not_visible` or `no_answer`)."""
        kind = "not_visible" if reason == "not_visible" else "no_answer"
        return self._response(ctx, "abstain", abstain_reason=reason,
                              notices=[Notice(kind=kind, text=text)])

    # ------------------------------------------------------------------ follow-ups

    def _standalone(self, ctx: Context, request: AskRequest) -> AskRequest:
        """The follow-up as one standalone question (answer.md "Follow-ups"). The model only
        rewrites text; which machine is meant is decided by the recognizer."""
        prev = request.previous
        out = self.llm.complete_json(
            self.model, prompts.followup(prev.question, request.question),
            prompts.FOLLOWUP_SCHEMA, config.PROMPT_FOLLOWUP, ctx.scope, ctx.meter)
        question = request.question
        rewritten = (out.get("standalone_question") or "").strip()[:2000]
        if out.get("continues") and rewritten:
            question = rewritten
        update: dict = {"question": question}
        if (request.asset_id is None and prev.asset_id in self.fleet.assets
                and not self._names_machine(recognize(request.question), prev.asset_id)):
            update["asset_id"] = prev.asset_id
        return request.model_copy(update=update)

    def _names_machine(self, rec: Recognized, previous_asset_id: str) -> bool:
        """Whether the message names a machine itself: an asset ID or serial, or another model."""
        if rec.asset_ids or rec.legacy_ids or rec.serials:
            return True
        return bool(rec.models) and self.fleet.assets[previous_asset_id].model not in rec.models

    # ------------------------------------------------------------------ did you mean

    def _did_you_mean(self, ctx: Context, q: str, rec: Recognized,
                      res: Resolution) -> AnswerResponse | None:
        """Clarify or abstain when the question names a model or asset ID that doesn't exist.
        A name only in documents hidden from the user counts as existing (it then abstains
        `not_visible` later), and only names the user may see are suggested."""
        if res.unknown and ASSET.fullmatch(res.unknown.strip()):
            unknown = res.unknown.strip().upper()
            matches = didyoumean.close_assets(unknown, set(self.fleet.assets))
            if matches:
                return self._suggest(ctx, q, unknown, matches)
            return None  # abstain unknown_asset as before
        visible_models = {a.model for a in self.fleet.assets.values()} | {
            m for d in ctx.docs.values() for m in d.models}
        for m in rec.models:
            if (m in visible_models or self.serving.identifier_search(ctx.groups, [m], 1)
                    or self.serving.hidden_exists(ctx.groups, [m], None, None)):
                continue
            matches = didyoumean.close_models(m, visible_models)
            if matches:
                return self._suggest(ctx, q, m, matches)
            return self._abstain(ctx, "no_permitted_source",
                                 f"{m} is not a model in the documents or the fleet records. "
                                 "Check the model name on the nameplate.")
        return None

    def _suggest(self, ctx: Context, q: str, name: str, matches: list[str]) -> AnswerResponse:
        """Clarify by offering the question rewritten with each close name."""
        options = [ClarifyOption(label=k, question=didyoumean.replace_name(q, name, k))
                   for k in matches]
        return self._response(ctx, "clarify", asset=None, clarification=Clarification(
            question=didyoumean.ask_text(matches), options=options))

    def _run(self, ctx: Context) -> AnswerResponse:
        """Resolve, retrieve, filter, check sufficiency, generate, validate, complete, assemble."""
        q = ctx.request.question
        rec = recognize(q)
        ctx.res = res = resolve(q, rec, self.fleet, ctx.request.asset_id)
        ctx.docs = self.serving.documents(ctx.groups)
        if not ctx.request.asset_id:
            dym = self._did_you_mean(ctx, q, rec, res)
            if dym:
                ctx.timer.lap("resolve")
                return dym
        if res.unknown:
            ctx.timer.lap("resolve")
            return self._abstain(ctx, "unknown_asset",
                                 f"No machine with the ID {res.unknown} is in the fleet records.")
        if len(res.candidates) > 1:
            per_asset = {a.asset_id: {b.doc_id: b.status
                                      for b in self.serving.bulletin_statuses(a.asset_id)
                                      if b.doc_id in ctx.docs}
                         for a in res.candidates}
            if candidates_differ(res.candidates, per_asset):
                ctx.timer.lap("resolve")
                return self._clarify(ctx, res)
        if ctx.asset:
            ctx.statuses = [b for b in self.serving.bulletin_statuses(ctx.asset.asset_id)
                            if b.doc_id in ctx.docs]
        ctx.timer.lap("resolve")

        cands, events_used = self._retrieve(ctx, rec)
        ctx.timer.lap("retrieve")

        models = res.models
        status_by_doc = {b.doc_id: b.status for b in ctx.statuses}
        asset_models = {a.asset_id: a.model for a in self.fleet.assets.values()}
        filtered = apply(cands, models, ctx.asset, self.relations, set(ctx.docs), status_by_doc,
                         asset_models)
        evidence = self._budget(filtered.evidence, events_used)
        visible = self.serving.visible_passages(ctx.groups, [c.pid for c in evidence])
        evidence = [c for c in evidence if c.pid in visible]
        uns = unsatisfied(self.procedures, ctx.groups)
        named = names_in(q + "\n" + "\n".join(c.passage.all_text for c in evidence), list(uns))
        ctx.timer.lap("filter")

        if not evidence:
            return self._no_evidence(ctx, rec, filtered.dropped_model, named, uns)

        labels = {f"P{i + 1}": c for i, c in enumerate(evidence)}
        evidence_text = "\n\n".join(prompts.evidence_block(lab, c, build.locator(c))
                                    for lab, c in labels.items())
        machine = prompts.machine_line(ctx.asset, models, [
            f"{ctx.docs[b.doc_id].title}: {b.status}"
            + (f", campaign {b.campaign_code}" if b.campaign_code else "")
            + (f" ({b.reason})" if b.status == "check_on_site" and b.reason else "")
            for b in ctx.statuses])

        suff = self.llm.complete_json(
            self.model, prompts.sufficiency(q, machine, evidence_text, [uns[n] for n in named]),
            prompts.SUFFICIENCY_SCHEMA, config.PROMPT_SUFFICIENCY, ctx.scope, ctx.meter)
        ctx.timer.lap("sufficiency")
        restricted = uns.get(suff.get("restricted_procedure") or "")
        if restricted and restricted.name not in named:
            restricted = None
        if not restricted:
            restricted, added = self._backstop(ctx, q, uns, named)
            if added:
                lab = f"P{len(labels) + 1}"
                labels[lab] = added
                evidence.append(added)
                named.append(restricted.name)
                evidence_text += "\n\n" + prompts.evidence_block(lab, added, build.locator(added))
        if not restricted:
            if suff.get("out_of_scope"):
                return self._abstain(ctx, "out_of_scope",
                                     "This question is outside what the copilot answers.")
            if not suff.get("covered"):
                return self._no_evidence(ctx, rec, filtered.dropped_model, [], uns,
                                         had_evidence=True)

        gen = self.llm.complete_json(
            self.model, prompts.generate(q, machine, evidence_text, bool(events_used), restricted),
            prompts.GENERATE_SCHEMA, config.PROMPT_GENERATE, ctx.scope, ctx.meter)
        gen = _without_labels(gen)
        ctx.timer.lap("generate")

        sentences = self._validate(ctx, gen.get("sentences", []), labels, machine, evidence_text,
                                   q, restricted, list(uns))
        ctx.timer.lap("validate")
        if config.COMPLETE_ENABLED and not restricted and sentences:
            sentences = self._complete(ctx, rec, sentences, labels, machine, q, list(uns))
            ctx.timer.lap("complete")
        return self._assemble(ctx, rec, gen, sentences, labels, filtered, evidence, restricted,
                              named, uns, events_used)

    # ------------------------------------------------------------------ stages

    def _clarify(self, ctx: Context, res: Resolution) -> AnswerResponse:
        """Ask which of the candidate machines is meant."""
        model = res.models[0] if res.models else "machine"
        site = res.candidates[0].site_name if res.site else None
        question = f"Which {model}" + (f" at {site}" if site else "") + "?"
        options = [ClarifyOption(asset_id=a.asset_id, label=f"{a.asset_id} ({a.serial})")
                   for a in sorted(res.candidates, key=lambda a: a.asset_id)]
        return self._response(ctx, "clarify", asset=None,
                              clarification=Clarification(question=question, options=options))

    def _retrieve(self, ctx: Context, rec) -> tuple[list[Candidate], list[str]]:
        """Ranked candidates from hybrid search plus service history, applying bulletins and
        controlled procedure bodies; also the history passage IDs used."""
        q, groups, asset = ctx.request.question, ctx.groups, ctx.asset
        ids = [i for i in rec.search_ids() if i not in rec.models]
        if asset:
            ids = list(dict.fromkeys([asset.asset_id, asset.serial, *ids]))
        emb = ctx.embedding = self.llm.embed(self.embedding_model, q, self.embedding_dims,
                                             ctx.meter)
        scores = retrieve(self.serving, groups, q, ids, emb,
                          keyword_ids=[*ids, *ctx.res.models])
        order = sorted(scores, key=lambda p: -scores[p])[:60]

        events_used: list[str] = []
        if asset and HISTORY.search(q):
            evs = self.serving.events(groups, asset.asset_id)
            codes = rec.fault_codes
            if codes:
                evs = [e for e in evs if e.fault_code in codes
                       or any(norm(c) in norm(e.notes) for c in codes)]
            events_used = [e.passage_id for e in evs[-config.HISTORY_EVENTS_MAX:]
                           if e.passage_id]

        # A bulletin that applies to this unit is given with its main sections.
        bulletin_ids: list[str] = []
        for b in ctx.statuses:
            pid = self._bulletin_passage(ctx, b)
            if pid and b.status in APPLYING:
                bulletin_ids.append(pid)
                rest = [p for p in ctx.bulletin_docs[b.doc_id]
                        if p.role != "child" and p.passage_id != pid]
                rest.sort(key=lambda p: -scores.get(p.passage_id, 0))
                doc_pids = {p.passage_id for p in ctx.bulletin_docs[b.doc_id]}
                relevant = b.status == "in_campaign" or bool(doc_pids & set(order[:20]))
                for i, p in enumerate(rest[:config.BULLETIN_PASSAGES]):
                    scores[p.passage_id] = (9.0 - i * 0.01 if relevant
                                            else max(scores.get(p.passage_id, 0), 0.01) * 2)
                    order.append(p.passage_id)

        passages = self.serving.passages(groups, [*order, *events_used, *bulletin_ids])
        parents = {p.parent_passage_id for p in passages.values() if p.parent_passage_id}
        passages.update(self.serving.passages(groups, sorted(parents - set(passages))))

        # A controlled procedure among the top hits is given with its procedure body.
        controlled = []
        for pid in order[:30]:
            d = ctx.docs.get(passages[pid].doc_id) if pid in passages else None
            if d and d.doc_type in CONTROLLED and d.doc_id not in controlled:
                controlled.append(d.doc_id)
        expanded, bodies = set(controlled[:3]), []
        for doc_id in controlled[:3]:
            best = max(scores.get(p.passage_id, 0) for p in passages.values()
                       if p.doc_id == doc_id)
            for p in self.serving.doc_passages(groups, doc_id):
                if p.role == "parent" and p.passage_id not in passages:
                    passages[p.passage_id] = p
                    scores[p.passage_id] = best
                    order.append(p.passage_id)
                    bodies.append(p.passage_id)

        # A controlled procedure named by a top hit is given with its body (longest section).
        by_name = {canonical_procedure(m): d.doc_id for d in ctx.docs.values()
                   if d.doc_type in CONTROLLED for m in [PROCEDURE.match(d.title)] if m}
        referenced: list[tuple[str, str]] = []
        for pid in [*events_used, *order[:config.REFERENCE_SCAN], *bodies]:
            p = passages.get(pid)
            if p is None:
                continue
            for m in PROCEDURE.finditer(p.all_text):
                doc_id = by_name.get(canonical_procedure(m))
                if not doc_id or doc_id == p.doc_id or doc_id in expanded:
                    continue
                expanded.add(doc_id)
                doc_ps = self.serving.doc_passages(groups, doc_id)
                body = max((q for q in doc_ps if q.role != "child"),
                           key=lambda q: len(q.text), default=None)
                if body is None:
                    continue
                best = max(scores.get(q.passage_id, 0) for q in doc_ps)
                passages.setdefault(body.passage_id, body)
                scores[body.passage_id] = max(scores.get(body.passage_id, 0), best * 1.01, 0.01)
                referenced.append((body.passage_id, pid))
                order.append(body.passage_id)

        # Prefer passages specific to the resolved model over general ones.
        asset_models = {a.asset_id: a.model for a in self.fleet.assets.values()}
        for pid, p in passages.items():
            d = ctx.docs.get(p.doc_id)
            if d and ctx.res.models and effective_models(p, d, asset_models) & set(
                    ctx.res.models):
                scores[pid] = scores.get(pid, 0) * config.MODEL_BOOST
        for body_pid, ref_pid in referenced:
            scores[body_pid] = max(scores[body_pid], scores.get(ref_pid, 0) * 0.95)
        order = sorted(dict.fromkeys(order), key=lambda p: -scores.get(p, 0))
        top = 10.0
        for pid in bulletin_ids + events_used:
            scores[pid] = top
            top -= 0.01
        ranked = consolidate(
            sorted(dict.fromkeys([*bulletin_ids, *events_used, *order]),
                   key=lambda p: -scores.get(p, 0)), passages)
        out = []
        for pid in ranked:
            p = passages.get(pid)
            doc = ctx.docs.get(p.doc_id) if p else None
            if p is None or doc is None:
                continue  # fail closed: no visible document record
            out.append(Candidate(p, doc, scores.get(pid, 0.0)))
        return out, [e for e in events_used if e in passages]

    def _bulletin_passage(self, ctx: Context, b: BulletinStatus) -> str | None:
        """Passage that supports a bulletin's status (its quote, else its page for this model),
        cached on the context with the bulletin's passages; None if not found."""
        if b.doc_id in ctx.bulletin_cites:
            return ctx.bulletin_cites[b.doc_id].pid
        doc = ctx.docs[b.doc_id]
        ps = self.serving.doc_passages(ctx.groups, b.doc_id)
        ctx.bulletin_docs[b.doc_id] = ps
        quote = norm(b.quote or "")[:80]
        best = next((p for p in ps if quote and quote in norm(p.all_text)), None)
        if best is None:
            best = next((p for p in ps if (p.anchor or {}).get("page") == b.page
                         and ctx.asset and ctx.asset.model in p.models), None)
        if best is None:
            return None
        ctx.bulletin_cites[b.doc_id] = Candidate(best, doc, bulletin_status=b.status)
        return best.passage_id

    def _budget(self, evidence: list[Candidate], events: list[str]) -> list[Candidate]:
        """Evidence within the count, per-document, record and character caps; history events
        skip the count caps but not the character cap."""
        out, chars, general, records = [], 0, 0, 0
        per_doc: dict[str, int] = {}
        for c in evidence:
            is_event = c.pid in events
            if not is_event and general >= config.EVIDENCE_MAX:
                continue
            if not is_event:
                d = c.doc
                cap = (config.PER_DOC_MAX_PRIMARY
                       if d.doc_type in CONTROLLED or c.bulletin_status in APPLYING
                       else config.PER_DOC_MAX_INFORMAL if d.authority_tier >= 5
                       else config.PER_DOC_MAX)
                if per_doc.get(d.doc_id, 0) >= cap:
                    continue
                if d.doc_type in RECORD_TYPES:
                    if records >= config.RECORDS_MAX:
                        continue
                    records += 1
                per_doc[d.doc_id] = per_doc.get(d.doc_id, 0) + 1
            size = min(len(c.passage.text), prompts.PASSAGE_MAX_CHARS)
            if chars + size > config.EVIDENCE_MAX_CHARS:
                continue
            out.append(c)
            chars += size
            general += 0 if is_event else 1
        return out

    def _hidden_exists(self, ctx: Context, rec) -> bool:
        """True when passages the user cannot see share the question's identifiers and are close
        to the question (serving.hidden_exists); reveals existence only, never content."""
        ids = [*(ctx.res.models if ctx.res else []), *rec.search_ids()]
        if ctx.asset:
            ids += [ctx.asset.asset_id, ctx.asset.serial]
        ids = list(dict.fromkeys(ids))
        if not ids or ctx.embedding is None:
            return False
        return self.serving.hidden_exists(ctx.groups, ids, ctx.embedding,
                                          config.HIDDEN_MAX_DISTANCE)

    def _backstop(self, ctx: Context, q: str, uns, named
                  ) -> tuple[Unsatisfied | None, Candidate | None]:
        """Restricted outcome decided by code (constitution V), whatever the sufficiency call
        said: a how-to question about work an unsatisfied procedure covers, by the scope in its
        published title. The procedure must be named in the evidence, else in a passage the user
        can see, which is then added to the evidence and cited. Only ever adds a restriction."""
        cover = covering(q, uns, config.COVER_MIN_TERMS)
        if cover is None:
            return None, None
        if cover.name in named:
            return cover, None
        ids = self.serving.keyword_search(ctx.groups, cover.name, config.COVER_NAMING_K)
        found = self.serving.passages(ctx.groups, ids)
        visible = self.serving.visible_passages(ctx.groups, list(found))
        asked = terms(q)
        naming = [found[pid] for pid in ids
                  if pid in visible and found[pid].doc_id in ctx.docs
                  and names_in(found[pid].all_text, [cover.name])]
        if not naming:
            return None, None
        _, best = max(enumerate(naming), key=lambda ip: (len(terms(ip[1].text) & asked), -ip[0]))
        return cover, Candidate(best, ctx.docs[best.doc_id])

    def _no_evidence(self, ctx: Context, rec, dropped, named, uns,
                     had_evidence: bool = False) -> AnswerResponse:
        """Abstain `not_visible` when a restricted procedure is named or hidden passages match,
        else `no_permitted_source` (noting other models dropped)."""
        if named:
            name = named[0]
            return self._abstain(ctx, "not_visible",
                                 f"{name} requires {', '.join(uns[name].missing_groups)}; its "
                                 "content is not visible to you.")
        if self._hidden_exists(ctx, rec):
            return self._abstain(ctx, "not_visible",
                                 "Information on this is not visible to you. Ask your team lead "
                                 "or a technician trained on this equipment.")
        target = ctx.asset.asset_id if ctx.asset else ", ".join(ctx.res.models) or None
        text = "No source you can see covers this" + (f" for the {target}." if target else ".")
        others = sorted({m for c in dropped for m in (c.passage.models or c.doc.models)}
                        - set(ctx.res.models))
        if others and ctx.res.models:
            text += (f" Information for other models ({', '.join(others[:3])}) does not apply "
                     "and was not used.")
        return self._abstain(ctx, "no_permitted_source", text)

    def _validate(self, ctx, raw, labels, machine, evidence_text, q, restricted,
                  unsatisfied_names) -> list[tuple[dict, list[Candidate]]]:
        """Sentences passing the restricted and citation checks, with their cited candidates;
        failures get one regeneration and are dropped if they still fail."""
        supplied = _supplied(labels)
        record = self._asset_record(ctx)
        markers = ctx.markers

        def verdict(s: dict) -> tuple[bool, str]:
            """(ok, reason) for one sentence."""
            text = s.get("text", "").strip()
            if not text:
                return False, "empty"
            if restricted and s.get("kind") == "step":
                return False, "steps are not allowed for a restricted procedure"
            hits = guard(text, unsatisfied_names, markers)
            if hits:
                return False, "restricted content: " + ", ".join(hits)
            v = check_sentence(text, list(s.get("cites", [])), supplied, record, q)
            return v.ok, v.reason

        verdicts = [verdict(s) for s in raw]
        failures = [(i, s.get("text", ""), why) for i, (s, (ok, why)) in
                    enumerate(zip(raw, verdicts, strict=True)) if not ok]
        fixed = dict(enumerate(raw))
        if failures:
            out = self.llm.complete_json(
                self.model, prompts.regenerate(q, machine, evidence_text, failures, restricted),
                prompts.REGENERATE_SCHEMA, config.PROMPT_REGENERATE, ctx.scope, ctx.meter)
            failed = {i for i, _, _ in failures}
            for f in out.get("fixes", []):
                i = f.get("index")
                if i in failed:
                    fixed[i] = None if f.get("drop") else {
                        **raw[i], "text": strip_labels(f.get("text", "")),
                        "cites": f.get("cites", [])}
            for i in failed:
                if fixed.get(i) is raw[i]:
                    fixed[i] = None
        kept = []
        for i in range(len(raw)):
            s = fixed.get(i)
            if s is None:
                continue
            if i in {f[0] for f in failures} and not verdict(s)[0]:
                continue
            cited = [labels[c] for c in dict.fromkeys(s.get("cites", [])) if c in labels]
            kept.append((s, cited))
        return kept

    def _complete(self, ctx, rec, kept, labels, machine, q,
                  unsatisfied_names) -> list[tuple[dict, list[Candidate]]]:
        """Completeness pass (answers only): code lists what the cited passages state and the
        answer leaves out; one model call adds what a technician needs. Additions pass the same
        citation, value and marker checks; one failing the citation check is dropped. A marker,
        or an addition too close to content hidden from the user, keeps the first answer."""
        cited_labels = list(dict.fromkeys(lab for s, _ in kept for lab in s.get("cites", [])
                                          if lab in labels))
        texts = [s["text"].strip() for s, _ in kept]
        items = complete.missing(texts, {lab: labels[lab].passage.text for lab in cited_labels},
                                 config.COMPLETE_MAX_ITEMS, q)
        items = [i for i in items if not complete.names_any(i.text, unsatisfied_names)]
        if not items:
            return kept
        evidence = "\n\n".join(prompts.evidence_block(lab, labels[lab], build.locator(labels[lab]))
                               for lab in cited_labels)
        out = self.llm.complete_json(
            self.model, prompts.complete(q, machine, evidence,
                                         [(s.get("kind", "statement"), t)
                                          for (s, _), t in zip(kept, texts, strict=True)],
                                         [(i.label, i.kind, i.text) for i in items],
                                         config.COMPLETE_MAX_ADDITIONS),
            prompts.COMPLETE_SCHEMA, config.PROMPT_COMPLETE, ctx.scope, ctx.meter)
        supplied = {lab: t for lab, t in _supplied(labels).items() if lab in cited_labels}
        record = self._asset_record(ctx)
        adds: list[tuple[int, dict]] = []
        for a in out.get("additions", [])[:config.COMPLETE_MAX_ADDITIONS]:
            text = strip_labels(a.get("text", "")).strip()
            cites = [c for c in dict.fromkeys(a.get("cites", [])) if c in supplied]
            if not text or a.get("kind") not in ("statement", "step", "warning"):
                continue
            if guard(text, unsatisfied_names, ctx.markers):
                return kept
            if (complete.names_any(text, unsatisfied_names)
                    or complete.repeats(text, texts + [s["text"] for _, s in adds])
                    or not check_sentence(text, cites, supplied, record, q).ok):
                continue
            adds.append((a.get("after", len(kept)),
                         {"kind": a["kind"], "step_number": None, "text": text, "cites": cites}))
        if not adds or self._close_to_hidden(ctx, rec, [(s["text"], [labels[c] for c in s["cites"]])
                                                        for _, s in adds]):
            return kept
        merged = [(s, [labels[c] for c in s["cites"]]) for after, s in adds if after < 0]
        for i, k in enumerate(kept):
            merged.append(k)
            merged += [(s, [labels[c] for c in s["cites"]]) for after, s in adds if after == i]
        merged += [(s, [labels[c] for c in s["cites"]]) for after, s in adds
                   if after >= len(kept)]
        return merged

    def _close_to_hidden(self, ctx: Context, rec,
                         sentences: list[tuple[str, list[Candidate]]]) -> bool:
        """True when a sentence is within `COMPLETE_HIDDEN_DISTANCE` of a passage the user cannot
        see that shares its identifiers (serving.hidden_exists; reveals nothing about it), and
        closer to it than to every passage the sentence cites (those it may restate)."""
        base = [*(ctx.res.models if ctx.res else []), *rec.search_ids()]
        if ctx.asset:
            base += [ctx.asset.asset_id, ctx.asset.serial, ctx.asset.model]

        def embed(text: str) -> list[float]:
            """Embedding metered to this request."""
            return self.llm.embed(self.embedding_model, text, self.embedding_dims, ctx.meter)

        with ThreadPoolExecutor(max_workers=min(8, len(sentences))) as pool:
            embs = list(pool.map(embed, [t for t, _ in sentences]))
        for (text, cited), emb in zip(sentences, embs, strict=True):
            r = recognize(text)
            ids = list(dict.fromkeys([*base, *r.search_ids(), *r.models]))
            limit = config.COMPLETE_HIDDEN_DISTANCE
            if not ids or not self.serving.hidden_exists(ctx.groups, ids, emb, limit):
                continue
            lo, hi = 0.0, limit
            for _ in range(10):
                mid = (lo + hi) / 2
                lo, hi = (lo, mid) if self.serving.hidden_exists(ctx.groups, ids, emb, mid) \
                    else (mid, hi)
            with ThreadPoolExecutor(max_workers=min(8, len(cited) or 1)) as pool:
                own = list(pool.map(embed, [c.passage.text[:prompts.PASSAGE_MAX_CHARS]
                                            for c in cited]))
            if not any(_distance(emb, v) <= hi for v in own):
                return True
        return False

    def _asset_record(self, ctx: Context) -> str:
        """The resolved machine as text sentences may rely on; empty without one."""
        a = ctx.asset
        if not a:
            return ""
        return (f"{a.asset_id} {a.model} serial {a.serial} firmware {a.firmware} "
                f"{a.site} {a.site_name} {a.region}")

    # ------------------------------------------------------------------ assembly

    def _assemble(self, ctx, rec, gen, kept, labels, filtered, evidence, restricted, named, uns,
                  events_used) -> AnswerResponse:
        """Final response: sentences, checked conflicts, restricted payload, notices and work order
        suggestion; abstains when nothing verified remains."""
        cites: dict[str, Candidate] = {}
        sentences: list[Sentence] = []
        step = 0
        for s, cited in kept:
            kind = s.get("kind", "statement")
            if kind == "step":
                step += 1
            for c in cited:
                cites[c.pid] = c
            sentences.append(Sentence(kind=kind, step_number=step if kind == "step" else None,
                                      segments=build.segments(s["text"].strip(), cited),
                                      citations=[c.pid for c in cited]))

        notices: list[Notice] = []
        conflicts = self._conflicts(gen.get("conflicts", []), labels, ctx, list(uns))
        for x in conflicts:
            for side in x.sides:
                for pid in side.citations:
                    cites[pid] = next(c for c in labels.values() if c.pid == pid)

        restricted_payload = None
        if restricted:
            naming = [c for c in evidence if names_in(c.passage.all_text, [restricted.name])]
            naming = naming or [c for _, cs in kept for c in cs]
            if not naming:
                return self._abstain(ctx, "not_visible",
                                     f"{restricted.name} requires "
                                     f"{', '.join(restricted.missing_groups)}; its content is "
                                     "not visible to you.")
            naming = naming[:3]
            for c in naming:
                cites[c.pid] = c
            restricted_payload = Restricted(procedure=restricted.name,
                                            missing_groups=list(restricted.missing_groups),
                                            citations=[c.pid for c in naming])
        elif not sentences:
            return self._abstain(ctx, "no_permitted_source",
                                 "No answer could be verified against the sources you can see.")

        notices += self._notices(ctx, filtered, sentences, cites, events_used)
        suggestion = self._suggestion(
            ctx, rec, gen.get("work_order") or {}, labels, cites, restricted, list(uns),
            restricted_payload.citations if restricted_payload else [], sentences,
            conflicts, evidence)
        if suggestion:
            for pid in suggestion.citations:
                cites.setdefault(pid, self._find(pid, labels, ctx))
        for c in ctx.bulletin_cites.values():
            cites.setdefault(c.pid, c)
        for n in notices:
            for pid in n.citations:
                cites.setdefault(pid, self._find(pid, labels, ctx, filtered))
        return self._response(
            ctx, "restricted" if restricted else "answer", sentences=sentences,
            citations={pid: build.citation(c) for pid, c in cites.items() if c is not None},
            conflicts=conflicts, notices=notices, restricted=restricted_payload,
            work_order_suggestion=suggestion)

    def _find(self, pid, labels, ctx, filtered=None) -> Candidate | None:
        """The candidate for `pid` among labelled, bulletin and set-aside ones; None if absent."""
        pools = [*labels.values(), *ctx.bulletin_cites.values()]
        if filtered:
            pools += filtered.superseded + filtered.stale
        return next((c for c in pools if c.pid == pid), None)

    def _conflicts(self, raw, labels, ctx, unsatisfied_names):
        """Conflicts with at least two checked sides citing different documents."""
        supplied = _supplied(labels)
        record = self._asset_record(ctx)
        markers = ctx.markers
        out = []
        for x in raw:
            sides = []
            for side in x.get("sides", []):
                stmt = side.get("statement", "").strip()
                cs = [c for c in side.get("cites", []) if c in labels]
                if (stmt and cs and check_sentence(stmt, cs, supplied, record,
                                                   ctx.request.question).ok
                        and not guard(stmt, unsatisfied_names, markers)):
                    sides.append((stmt, [labels[c] for c in dict.fromkeys(cs)]))
            docs = {c.doc.doc_id for _, cs in sides for c in cs}
            if len(sides) >= 2 and len(docs) >= 2 and x.get("topic", "").strip():
                out.append(build.conflict(x["topic"].strip(), sides))
        return out

    def _notices(self, ctx, filtered, sentences, cites, events_used) -> list[Notice]:
        """Notices: bulletins, superseded or stale sources (two documents each), unverified
        values, translations and service history."""
        out: list[Notice] = []
        for b in ctx.statuses:
            c = ctx.bulletin_cites.get(b.doc_id)
            title = ctx.docs[b.doc_id].title
            pid = [c.pid] if c else []
            if b.status == "check_on_site":
                out.append(Notice(kind="check_on_site", citations=pid,
                                  text=f"{title}: whether it applies depends on a condition to "
                                       f"check at the machine: {b.reason or 'see the bulletin'}"))
            elif b.status in ("affected", "in_campaign"):
                text = f"{title} applies to this unit"
                text += f" (campaign {b.campaign_code})." if b.campaign_code else "."
                out.append(Notice(kind="bulletin", text=text, citations=pid))
        for kind, pool, verb in (("superseded", filtered.superseded, "is superseded"),
                                 ("possibly_stale", filtered.stale, "may be out of date")):
            seen = set()
            for c in pool:
                if c.doc.doc_id in seen or c.score <= 0:
                    continue
                seen.add(c.doc.doc_id)
                if len(seen) > 2:
                    break
                out.append(Notice(kind=kind, citations=[c.pid],
                                  text=f"{c.doc.title} {verb}; a newer source you can see is used "
                                       "instead."))
        if any(seg.kind == "unverified" for s in sentences for seg in s.segments):
            pages = sorted({seg.page for s in sentences for seg in s.segments
                            if seg.kind == "unverified" and seg.page})
            out.append(Notice(kind="unverified_value",
                              citations=sorted({pid for s in sentences for seg in s.segments
                                                if seg.kind == "unverified"
                                                for pid in [seg.page_image_passage_id] if pid}),
                              text="A value could not be verified from the scan. Check scanned "
                                   f"page {', '.join(map(str, pages))}."))
        translated = [pid for pid, c in cites.items() if c.passage.text_en
                      and (c.passage.lang or "en") != "en"]
        if translated:
            out.append(Notice(kind="translated", citations=translated[:3],
                              text="Some sources are machine translations; the viewer shows the "
                                   "original text."))
        used_events = [pid for pid in events_used if pid in cites]
        if used_events:
            out.append(Notice(kind="history", citations=used_events,
                              text="Service history from records you can see was used."))
        return out

    def _suggestion(self, ctx, rec, wo, labels, cites, restricted, unsatisfied_names,
                    restricted_cites, sentences, conflicts=(), evidence=()):
        """Work order suggestion for a restricted procedure, a needed work order or a campaign;
        None without a machine unless it is a referral or parts order."""
        asset = ctx.asset
        campaign = next((b.campaign_code for b in ctx.statuses
                         if b.status == "in_campaign" and b.campaign_code), None)
        if not (restricted or wo.get("needed") or campaign):
            return None
        cited = list(cites.values())
        wo_cites = [labels[c] for c in wo.get("cites", []) if c in labels]
        texts = [c.passage.all_text for c in [*cited, *wo_cites]]
        parts = [] if restricted else build.parts(wo.get("parts", []), [*cited, *wo_cites])
        if not asset and not (restricted or parts):
            return None  # without a machine, only a safety referral or a parts order is useful
        fault = next((f for f in rec.fault_codes if build.fault_in(f, texts)), None)
        certs: list[str] = []
        if restricted:
            certs = [g for g in restricted.missing_groups if g.startswith("cert-")]
        else:
            said = "\n".join([*(seg.text or "" for s in sentences for seg in s.segments),
                              *(side.statement for c in conflicts for side in c.sides)])
            for name in names_in(said, list(self.cert_groups)):
                certs += self.cert_groups[name]
        for name in self._procedures_in(evidence):
            certs += self.cert_groups.get(name, [])
        supplied = _supplied(labels)
        summary = (wo.get("summary") or "").strip()
        labs = [c for c in wo.get("cites", []) if c in labels] or [
            lab for lab, c in labels.items() if c.pid in cites]
        markers = ctx.markers
        if (not summary or not check_sentence(summary, labs, supplied,
                                              self._asset_record(ctx), ctx.request.question).ok
                or guard(summary, unsatisfied_names, markers)):
            target = asset.asset_id if asset else (", ".join(ctx.res.models) or "the machine")
            summary = f"{fault} on {target}" if fault else f"Work on {target}"
            if restricted:
                summary += f", needs {restricted.name}"
        sugg_cites = list(dict.fromkeys(
            [c.pid for c in wo_cites] + [ctx.bulletin_cites[b.doc_id].pid for b in ctx.statuses
                                         if b.campaign_code == campaign and campaign
                                         and b.doc_id in ctx.bulletin_cites]
            + list(restricted_cites)))
        return WorkOrderSuggestion(asset_id=asset.asset_id if asset else None, fault_code=fault,
                                   summary=summary,
                                   required_certification=sorted(set(certs)), parts=parts,
                                   campaign_code=campaign, citations=sugg_cites)

    def _procedures_in(self, evidence) -> set[str]:
        """Restricted procedures whose own passages, or passages tagged with them, are in the
        evidence: the work needs their certification whatever the model wrote."""
        by_doc = {p.doc_id: p.name for p in self.procedures}
        names = {p.name for p in self.procedures}
        out = set()
        for c in evidence:
            if c.doc.doc_id in by_doc:
                out.add(by_doc[c.doc.doc_id])
            out.update(tag for tag in c.passage.restricted_tags if tag in names)
        return out

    def _resolved_asset(self, ctx: Context) -> ResolvedAsset | None:
        """The resolved machine with its bulletin statuses, or None."""
        a = ctx.asset
        if not a:
            return None
        bulletins = []
        for b in ctx.statuses:
            c = ctx.bulletin_cites.get(b.doc_id)
            bulletins.append(AssetBulletin(doc_id=b.doc_id, title=ctx.docs[b.doc_id].title,
                                           status=b.status, campaign_code=b.campaign_code,
                                           reason=b.reason, citations=[c.pid] if c else []))
        return ResolvedAsset(asset_id=a.asset_id, model=a.model, serial=a.serial,
                             firmware=a.firmware, site=a.site, site_name=a.site_name,
                             region=a.region, bulletins=bulletins)


def build_engine(offline: bool = False) -> Engine:
    """`ANSWER_FRESH=1` skips model-cache reads (for a fresh evaluation run); default off."""
    from copilot_answer.llm import HostedLLM
    from copilot_answer.serving import PgServing

    fresh = os.environ.get("ANSWER_FRESH") == "1"
    return Engine(PgServing(), HostedLLM(offline=offline, fresh=fresh))
