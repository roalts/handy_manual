"""One evaluation run: every case through the API, every check, every failure categorized."""
import time
from dataclasses import dataclass, field

from pydantic import ValidationError

from copilot_contracts import AnswerResponse
from copilot_eval import categorize, citations, disclosure
from copilot_eval.cases import Case
from copilot_eval.categorize import Failure
from copilot_eval.client import Api, InfrastructureError
from copilot_eval.facts import FactResult, in_text, match, units
from copilot_eval.reference import Reference


@dataclass
class CaseResult:
    case: Case
    response: AnswerResponse
    seconds: float
    facts: list[FactResult]
    forbidden: list[FactResult]
    failures: list[Failure]
    disclosure_stats: dict
    sources_checked: int
    cost_usd: float | None = None
    calls: list[dict] = field(default_factory=list)
    sources: dict[str, dict] = field(default_factory=dict)

    @property
    def outcome_ok(self) -> bool:
        """No outcome failure: status, abstain reason and restricted procedure as expected."""
        return not any(f.check == "outcome" for f in self.failures)

    @property
    def complete(self) -> bool:
        """Every required fact was found."""
        return all(f.hit for f in self.facts)


def _outcome_failures(case: Case, resp: AnswerResponse, visible: dict[str, str]) -> list[Failure]:
    """A wrong status alone; or, with the right status, a wrong abstain reason, restricted
    procedure or missing groups."""
    out = []
    if resp.status not in case.outcomes:
        in_visible = any(in_text(f, t) for f in case.required for t in visible.values())
        out.append(Failure(case.id, "outcome",
                           categorize.outcome(case.outcomes, resp.status, in_visible), False,
                           f"expected {' or '.join(case.outcomes)}, got {resp.status}"
                           + (f" ({resp.abstain_reason})" if resp.abstain_reason else "")))
        return out
    if resp.status == "abstain" and case.abstain_reason and \
            resp.abstain_reason != case.abstain_reason:
        out.append(Failure(case.id, "outcome", "policy", False,
                           f"abstain reason {resp.abstain_reason}, expected "
                           f"{case.abstain_reason}"))
    if resp.status == "restricted" and resp.restricted:
        if case.restricted_procedures and \
                resp.restricted.procedure not in case.restricted_procedures:
            out.append(Failure(case.id, "outcome", "policy", False,
                               f"restricted by {resp.restricted.procedure}, expected "
                               f"{' or '.join(case.restricted_procedures)}"))
        if case.restricted_missing and \
                set(case.restricted_missing) - set(resp.restricted.missing_groups):
            out.append(Failure(case.id, "outcome", "policy", False,
                               f"missing groups {resp.restricted.missing_groups}, expected "
                               f"{list(case.restricted_missing)}"))
    return out


def evaluate(case: Case, raw: dict, seconds: float, api: Api, ref: Reference,
             groups: frozenset[str], embed) -> CaseResult:
    """Every check on one raw response; InfrastructureError if it breaks the answer contract."""
    try:
        resp = AnswerResponse.model_validate(raw)
        resp.check()
    except (ValidationError, ValueError) as e:
        raise InfrastructureError(f"{case.id}: response breaks the answer contract: {e}") from e
    visible = ref.visible_texts(groups)
    failures = _outcome_failures(case, resp, visible)

    asked = " ".join(filter(None, [case.question, resp.question_used,
                                   (case.previous or {}).get("question")]))
    cit_failures, fetched = citations.check(resp, lambda pid: api.source(case.user_id, pid),
                                            asked)
    for f in cit_failures:
        if f.rule == "label":
            failures.append(Failure(case.id, "format", "generation", False,
                                    f"{f.where}: {f.detail}"))
            continue
        category = "policy" if f.rule == "hidden" else "citation"
        failures.append(Failure(case.id, "citation", category, True,
                                f"{f.where}: {f.detail}"))
    cited = {pid: f"{b.get('title') or ''}\n{b.get('text_original') or ''}\n"
                  f"{b.get('text_en') or ''}" for pid, b in fetched.items()}

    resp_units = units(resp)
    facts = [match(f, resp_units) for f in case.required]
    for r in facts:
        if not r.hit:
            category, evidence = categorize.missed_fact(r.fact, cited, visible)
            failures.append(Failure(case.id, "fact", category, False,
                                    f"missing: {r.fact.fact}", evidence))
    forbidden = [match(f, resp_units) for f in case.forbidden]
    for r in forbidden:
        if r.hit:
            failures.append(Failure(case.id, "forbidden", r.fact.category or "generation", False,
                                    f"present: {r.fact.fact}", r.evidence or ""))

    found, stats = disclosure.check(resp, groups, ref.procedures(), ref.markers(),
                                    ref.procedure_steps(), embed,
                                    {pid: t for pid, t in cited.items() if pid in visible})
    for d in found:
        failures.append(Failure(case.id, "disclosure", "policy", True,
                                f"{d.procedure} ({d.rule}): {d.detail}"))
    return CaseResult(case, resp, seconds, facts, forbidden, failures, stats, len(fetched),
                      sources=fetched)


@dataclass
class Run:
    started: float
    finished: float = 0.0
    dataset_version: str = ""
    results: list[CaseResult] = field(default_factory=list)
    grid: dict | None = None
    extra_failures: list[Failure] = field(default_factory=list)

    @property
    def failures(self) -> list[Failure]:
        """Every case failure plus the run-level ones (the access grid)."""
        return [f for r in self.results for f in r.failures] + self.extra_failures

    @property
    def blocking(self) -> list[Failure]:
        """Release-blocking failures only."""
        return [f for f in self.failures if f.blocking]


def run(cases: list[Case], api: Api, ref: Reference, users: dict[str, frozenset[str]],
        embed, progress=print) -> Run:
    """Ask and check every case as its user, closing the API clients at the end. Stops with
    InfrastructureError if the API serves another dataset version than the reference data."""
    out = Run(started=time.time())
    health = api.health()
    out.dataset_version = health.get("dataset_version", "")
    if out.dataset_version != ref.dataset_version():
        raise InfrastructureError(f"API serves {out.dataset_version}, serving schema has "
                                  f"{ref.dataset_version()}")
    try:
        for case in cases:
            raw, seconds = api.ask(case.user_id, case.question, case.previous)
            result = evaluate(case, raw, seconds, api, ref, users[case.user_id], embed)
            out.results.append(result)
            progress(f"{case.id:12} {case.user_id} {result.response.status:10} "
                     f"{seconds:5.1f} s  failures {len(result.failures)}"
                     f"{' BLOCKING' if any(f.blocking for f in result.failures) else ''}")
    finally:
        api.close()
    out.finished = time.time()
    return out
