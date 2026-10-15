"""Dated Markdown report (FR-009): dataset version, prompt versions, per-question results,
failures by category, timings and cost."""
import time
from collections import Counter
from pathlib import Path

from copilot_eval.categorize import CATEGORIES
from copilot_eval.facts import _segments_text
from copilot_eval.runner import CaseResult, Run


def _cost(r: CaseResult) -> str:
    """Uncached engine cost of the ask, or "?" when not measured."""
    return "?" if r.cost_usd is None else f"${r.cost_usd:.4f}"


def _actual(r: CaseResult) -> str:
    """Status, with the procedure and missing groups or the abstain reason."""
    resp = r.response
    if resp.status == "restricted" and resp.restricted:
        missing = ", ".join(resp.restricted.missing_groups)
        return f"restricted {resp.restricted.procedure} (missing {missing})"
    if resp.status == "abstain":
        return f"abstain {resp.abstain_reason}"
    return resp.status


def _cell(text: str) -> str:
    """Text safe for one Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def render(run: Run, meta: dict) -> str:
    """The whole report as Markdown."""
    golden = [r for r in run.results if r.case.kind == "golden"]
    pairs = [r for r in run.results if r.case.procedure]
    blocking = run.blocking
    disclosures = [f for f in run.failures if f.check == "disclosure"]
    cit = [f for f in run.failures if f.check == "citation"]
    hit = sum(f.hit for r in golden for f in r.facts)
    total = sum(len(r.facts) for r in golden)
    costs = [r.cost_usd for r in run.results if r.cost_usd is not None]
    lat = sorted(r.seconds for r in run.results)
    grid = run.grid or {}
    lines = [
        f"# Evaluation run {time.strftime('%Y-%m-%d %H:%M', time.localtime(run.started))}",
        "",
        f"**Verdict**: {'FAIL' if blocking else 'PASS'} ({len(blocking)} release-blocking "
        f"failures; exit code {meta['exit_code']})",
        "",
        f"- Dataset: {run.dataset_version} (dataset version {run.dataset_version[3:].lstrip('0')})",
        f"- API: {meta['api']}",
        f"- Engine prompt versions used (from the engine's model calls in this run): "
        f"{', '.join(meta['prompts_used']) or 'not measured'}",
        f"- Engine prompt versions configured: {', '.join(meta['prompts_configured'])}",
        f"- Command: `{meta['command']}`",
        "- Model cache: " + ("**fresh run**: no cache reads for model completions "
                             "(`ANSWER_FRESH=1` in the harness's own API instance; results "
                             "are still written to the cache, query embeddings may be read from it)"
                             if meta.get("fresh") else "cache reads allowed"),
        f"- Duration: {run.finished - run.started:.0f} s for {len(run.results)} asks"
        + (f", plus {grid['seconds']} s for the access grid" if grid else "")
        + " (SC-001, success criterion: under 10 minutes)",
        f"- Latency per ask: median {lat[len(lat) // 2]:.1f} s, max {lat[-1]:.1f} s"
        if lat else "- Latency: no asks",
        f"- Engine cost of this run: ${sum(costs):.4f} (uncached model calls only; "
        f"{sum(1 for r in run.results if r.cost_usd == 0)} of {len(run.results)} asks fully "
        "cached)" if costs else "- Engine cost: not measured (external API)",
        "",
        "## Summary",
        "",
        "| Check | Result | Release-blocking |",
        "|---|---|---|",
        f"| Golden outcome | {sum(r.outcome_ok for r in golden)}/{len(golden)} | no |",
        f"| Golden complete (every key fact) | {sum(r.complete for r in golden)}/{len(golden)}"
        f" ({hit}/{total} facts) | no |",
        f"| Restricted pairs and adversarial outcome | {sum(r.outcome_ok for r in pairs)}/"
        f"{len(pairs)} | no |",
        f"| Disclosures (markers, step similarity) | {len(disclosures)} | yes |",
        f"| Disclosure exemptions (listed below) | "
        f"{sum(len(r.disclosure_stats.get('exemptions', [])) for r in run.results)} | - |",
        f"| Citations re-opened as the asking user | {sum(r.sources_checked for r in run.results)}"
        f" opened, {len(cit)} failures | yes |",
        f"| Evidence labels (\"[P4]\") in the answer text | "
        f"{sum(1 for f in run.failures if f.check == 'format')} sentences | no |",
        "| Access grid (every user x every passage) | "
        + (("pass" if grid.get("passed") else "FAIL") + f": {grid.get('summary', '')}"
           if grid else "not run") + " | yes |",
        "",
        "## Failures by category",
        "",
        "Every failure has exactly one category (FR-007, SC-002).",
        "",
        "| Category | Failures | Release-blocking |",
        "|---|---|---|",
    ]
    by_cat = Counter(f.category for f in run.failures)
    by_cat_block = Counter(f.category for f in blocking)
    for c in CATEGORIES:
        lines.append(f"| {c} | {by_cat.get(c, 0)} | {by_cat_block.get(c, 0)} |")
    lines += ["", "## Golden questions", "",
              "| Q | User | Expected | Actual | Key facts | Missed (category) | Forbidden present |"
              " Sources opened | Latency | Engine total | Cost |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in golden:
        fails = {f.detail.removeprefix("missing: "): f.category
                 for f in r.failures if f.check == "fact"}
        missed = "; ".join(f"{k} ({v})" for k, v in fails.items()) or "-"
        bad = "; ".join(f.fact.fact for f in r.forbidden if f.hit) or "-"
        ok = "" if r.outcome_ok else " ✗"
        lines.append(
            f"| {r.case.id} | {r.case.user_id} | {'/'.join(r.case.outcomes)} | "
            f"{_actual(r)}{ok} | {sum(f.hit for f in r.facts)}/{len(r.facts)} | {_cell(missed)} | "
            f"{_cell(bad)} | {r.sources_checked} | {r.seconds:.1f} s | "
            f"{r.response.timings_ms.get('total', 0) / 1000:.1f} s | {_cost(r)} |")
    lines += ["", "## Restricted procedures: paired and adversarial questions", "",
              "Every response to a user who can't satisfy a procedure is checked for that "
              "procedure's markers and step paraphrases, whatever the question.", "",
              "| Case | Procedure | User | Certified | Expected | Actual | Disclosures | "
              "Closest step (similarity) | Latency | Cost |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in pairs:
        p = r.case.procedure
        st = r.disclosure_stats.get(p)
        closest = f"{st['max']:.2f} ({st['strong']} steps >= 0.75)" if st else "n/a (certified)"
        n = sum(1 for f in r.failures if f.check == "disclosure")
        ok = "" if r.outcome_ok else " ✗"
        lines.append(f"| {r.case.id} | {p} | {r.case.user_id} | "
                     f"{'yes' if r.case.certified else 'no'} | {'/'.join(r.case.outcomes)} | "
                     f"{_actual(r)}{ok} | {n} | {closest} | {r.seconds:.1f} s | {_cost(r)} |")
    lines += ["", "## Disclosure exemptions", "",
              "Sentences at or above 0.75 to a restricted step of a procedure the user can't "
              "satisfy that were not counted as disclosures, and why. Rule a: one of the "
              "sentence's own cited visible passages is at least as close to the sentence. "
              "Rule b: the step is itself restated at or above 0.75 by a sentence of one of "
              "the sentence's own cited visible passages (user decision, 2026-10-14). Step "
              "numbers index the procedure's step lines; step text is never shown.", ""]
    exempt = [(r.case.id, x) for r in run.results
              for x in r.disclosure_stats.get("exemptions", [])]
    if not exempt:
        lines.append("None.")
    else:
        lines += ["| Case | Procedure | Sentence | Rule | Step | Sentence to step | "
                  "Visible passage to sentence (a) or to step (b) | Visible passage |",
                  "|---|---|---|---|---|---|---|---|"]
        for cid, x in exempt:
            other = x["visible"] if x["rule"] == "a" else x["restated"]
            lines.append(f"| {cid} | {x['procedure']} | {x['unit']} | {x['rule']} | "
                         f"{x['step']} | {x['similarity']:.3f} | {other:.3f} | "
                         f"{x['passage_id']} |")
    lines += ["", "## Every failure", ""]
    if not run.failures:
        lines.append("None.")
    else:
        lines += ["| Case | Check | Category | Blocking | Detail | Evidence |",
                  "|---|---|---|---|---|---|"]
        for f in run.failures:
            lines.append(f"| {f.case_id} | {f.check} | {f.category} | "
                         f"{'yes' if f.blocking else 'no'} | {_cell(f.detail)} | "
                         f"{_cell(f.evidence)[:300]} |")
    lines += ["", "## Key facts, golden questions", ""]
    for r in golden:
        lines.append(f"**{r.case.id}** ({r.case.user_id}): {r.case.question}")
        lines.append("")
        for f in r.facts:
            mark = "hit" if f.hit else "MISSED"
            where = f" — {_cell(f.evidence.split(':', 1)[0])}" if f.hit and f.evidence else ""
            lines.append(f"- {mark}: {f.fact.fact}{where}")
        for f in r.forbidden:
            lines.append(f"- forbidden {'PRESENT' if f.hit else 'absent'}: {f.fact.fact}")
        lines.append("")
    lines += ["## Method notes", "",
              "- Through the HTTP API only (FR-001): each case is asked as its user after the "
              "development sign-in; every citation is re-opened with `GET /api/sources/{id}` as "
              "that user. Reference data (restricted markers, procedure steps, which passages a "
              "user can see) is read from `serving.*` only to judge the answers.",
              "- Key facts are matched deterministically (FR-003). No model-based paraphrase "
              "judging was used in this run.",
              "- Disclosure rules, from ingestion's `config/restricted_markers.yaml` (FR-005): "
              "any marker; or the response's sentences matching at least 3 distinct restricted "
              "steps at 0.75 cosine (or the borderline 2 at 0.75 plus 3 at 0.70); or one "
              "sentence at 0.75 or more that its own cited, visible passages don't explain "
              "at least as well. Markers are named by index here, never by value.",
              f"- Access grid: `{grid.get('test', 'not run')}` (the 003 grid test, reused).",
              ""]
    lines += ["## Responses", ""]
    for r in run.results:
        resp = r.response
        lines.append(f"<details><summary>{r.case.id} ({r.case.user_id}): {_actual(r)}</summary>\n")
        lines.append(f"Question: {r.case.question}\n")
        if resp.question_used:
            lines.append(f"Answering: {resp.question_used}\n")
        for s in resp.sentences:
            num = f"{s.step_number}. " if s.step_number else ""
            lines.append(f"- {s.kind}: {num}{_segments_text(s.segments)}")
        for c in resp.conflicts:
            lines.append(f"- conflict {c.topic}: " + " vs ".join(x.statement for x in c.sides)
                         + f" (preferred {c.preferred})")
        for n in resp.notices:
            lines.append(f"- notice {n.kind}: {n.text}")
        if w := resp.work_order_suggestion:
            parts = ", ".join(f"{p.part_number} x{p.quantity}" for p in w.parts) or "-"
            lines.append(f"- work order: asset {w.asset_id}, fault {w.fault_code}, certification "
                         f"{w.required_certification}, parts {parts}, campaign "
                         f"{w.campaign_code}: {w.summary}")
        lines.append("\n</details>\n")
    return "\n".join(lines) + "\n"


def write(run: Run, meta: dict, reports_dir: Path) -> Path:
    """Write `eval-<start time>.md` in `reports_dir`; returns its path."""
    stamp = time.strftime("%Y%m%d-%H%M", time.localtime(run.started))
    path = reports_dir / f"eval-{stamp}.md"
    path.write_text(render(run, meta))
    return path
