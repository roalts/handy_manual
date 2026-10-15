"""Run report (FR-037): every source file with exactly one outcome, counts, validation."""
from collections import Counter
from pathlib import Path

from copilot_ingest.artifacts import save_json


def write_report(out_dir: Path, data: dict) -> Path:
    """Write report.json and a Markdown report.md to `out_dir`; return the report.md path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    save_json(out_dir / "report.json", data)
    lines = [f"# Ingestion run {data['run_id']}", "",
             f"- Dataset version: `{data.get('dataset_version')}`",
             f"- Outcome: **{data['outcome']}**",
             f"- Provider: {data.get('provider')}", ""]

    files = data.get("files", [])
    lines += ["## Source files", "", f"{len(files)} files: " + ", ".join(
        f"{n} {k}" for k, n in sorted(Counter(f["outcome"] for f in files).items())), "",
        "| File | Outcome | Detail | Passages |", "|---|---|---|---|"]
    for f in files:
        lines.append(f"| `{f['path']}` | {f['outcome']} | {f.get('detail', '')} | "
                     f"{f.get('passages', '')} |")
    if files:
        no_rule = sum(1 for f in files if f["outcome"] == "quarantined:no_access_rule")
        lines += ["", f"Access-rule coverage: {len(files) - no_rule}/{len(files)} files "
                      f"({100 * (len(files) - no_rule) / len(files):.1f}%)"]
    if data.get("removed"):
        lines += ["", "Removed since last run: " + ", ".join(f"`{p}`" for p in data["removed"])]
    if data.get("acl_without_file"):
        lines += ["", "Access rules without a file: " +
                  ", ".join(f"`{p}`" for p in data["acl_without_file"])]

    changes = data.get("changes")
    if changes:
        lines += ["", "## Changes" + (f" since {changes['compared_with']}"
                                      if changes.get("compared_with") else ""), ""]
        lines += [f"- {k.replace('_', ' ')}: {v}" for k, v in changes.items()
                  if k != "compared_with"]
    counts = data.get("counts", {})
    if counts:
        lines += ["", "## Dataset", ""] + [f"- {k}: {v}" for k, v in counts.items()]
    history = data.get("history")
    if history:
        lines += ["", "## Service history", ""] + [f"- {k}: {v}" for k, v in history.items()]
    ocr = data.get("ocr")
    if ocr:
        lines += ["", "## Scanned pages (OCR)", ""]
        for path, s in ocr.items():
            if "pages" not in s:
                lines.append(f"- `{path}`: {s.get('status')}")
                continue
            lines.append(f"- `{path}`: {s['pages']} pages; {s['checked']} critical values "
                         f"checked against Tesseract, {s['verified']} verified, {s['withheld']} "
                         f"withheld for review" + (f", {s['reviewer']} set by a reviewer"
                                                   if s["reviewer"] else ""))
            for c in s["corrections"]:
                lines.append(f"  - page {c['page']}: model code {c['read']} read by "
                             f"{c['read_by']} corrected to {c['corrected']}")
    partial = [f for f in data.get("files", []) if f["outcome"] == "partial"]
    if partial:
        lines += ["", "## Partial documents", ""]
        lines += [f"- `{f['path']}`: {f['detail']}" for f in partial]
    tr = data.get("translation")
    if tr:
        lines += ["", "## Translation", ""] + [f"- {k.replace('_', ' ')}: {v}"
                                                for k, v in tr.items()]
    meta = data.get("metadata")
    if meta:
        lines += ["", "## Document metadata", "",
                  "- Revision and issue-date fields by source: " + ", ".join(
                      f"{k} {v}" for k, v in sorted(meta["fields_by_source"].items())),
                  f"- Fields left empty and sent to review: {meta['unverified']}"]
        lines += [f"- {s}" for s in meta["superseded"]]
    bulletins = data.get("bulletins")
    if bulletins:
        lines += ["", "## Bulletin applicability", "", "| Bulletin | Unit | Status |",
                  "|---|---|---|"]
        for title, b in bulletins.items():
            for unit, status in sorted(b["units"].items()):
                lines.append(f"| {title} | {unit} | {status} |")
        for title, b in bulletins.items():
            for q in b["conditions"]:
                lines.append(f"\n- {title}: condition the fleet register cannot decide: “{q}”")
    stale = data.get("stale")
    if stale:
        lines += ["", f"## Possibly stale passages ({len(stale['passages'])})", "",
                  f"Topic check: {stale['topic_check']}.", ""]
        lines += [f"- {s['doc']} › {s['heading']}: newer source {s['newer']}"
                  + (f" (topic similarity {s['topic_similarity']})"
                     if s["topic_similarity"] is not None else "")
                  for s in stale["passages"]]
    restricted = data.get("restricted")
    if restricted:
        lines += ["", "## Restricted procedures", ""]
        for p in restricted.get("procedures", []):
            lines.append(f"- {p['name']} ({', '.join(p['groups'])}): markers "
                         f"{', '.join(p['markers']) or 'none'}"
                         + (f"; awaiting approval: {', '.join(p['proposed'])}"
                            if p["proposed"] else ""))
        lines.append(f"- Passages tagged outside their procedure: {len(restricted['tagged'])}")
        for pid, why in restricted["tagged"].items():
            lines.append(f"  - `{pid}`: {'; '.join(why)}")
        if not restricted.get("similarity_checked"):
            lines.append("- Similarity check not run (no embeddings); only marker matching "
                         "applied.")

    lines += ["", "## Validation", "", "| Check | Result | Detail |", "|---|---|---|"]
    for v in data.get("validation", []):
        mark = "pass" if v["passed"] else ("FAIL" if v["severity"] == "error" else "warn")
        lines.append(f"| {v['name']} | {mark} | {v['detail']} |")

    review = data.get("review", [])
    lines += ["", f"## Review queue ({len(review)} open)", ""]
    for kind, n in sorted(Counter(r["kind"] for r in review).items()):
        lines += [f"### {kind} ({n})", "",
                  "| Item | Source | Field | Reason |", "|---|---|---|---|"]
        for r in (x for x in review if x["kind"] == kind):
            lines.append(f"| `{r['item_id'][:12]}` | `{r.get('path') or '-'}` | "
                         f"{r.get('field') or ''} | {r.get('reason') or ''} |")
        lines.append("")
    lines.append("Inspect with `copilot-ingest review show ITEM`; decide with "
                 "`copilot-ingest review resolve ITEM --value ...` (applied on the next run).")
    applied = data.get("decisions_applied", [])
    lines += ["", f"Reviewer decisions applied this run: {len(applied)}"]
    if data.get("errors"):
        lines += ["", "## Errors", ""] + [f"- {e}" for e in data["errors"]]
    path = out_dir / "report.md"
    path.write_text("\n".join(lines) + "\n")
    return path
