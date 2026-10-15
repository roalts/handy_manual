import json
from pathlib import Path
from typing import Annotated

import typer

from copilot_ingest.db.repo import connect, dataset_versions, migrate, published_version
from copilot_ingest.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False)
db_app = typer.Typer(no_args_is_help=True)
review_app = typer.Typer(no_args_is_help=True)
app.add_typer(db_app, name="db", help="Database setup")
app.add_typer(review_app, name="review", help="Review queue")


@db_app.command("init")
def db_init() -> None:
    """Create control, cache and pgvector. Idempotent."""
    applied = migrate()
    typer.echo(f"applied: {', '.join(applied)}" if applied else "database up to date")


@app.command()
def run(
    corpus: Annotated[Path | None, typer.Option(help="Corpus root")] = None,
    acl: Annotated[Path | None, typer.Option(help="Access rules file")] = None,
    users: Annotated[Path | None, typer.Option(help="Users and groups file")] = None,
    only: Annotated[list[str] | None, typer.Option(
        help="Re-extract only these files; the rest reuse cached extraction")] = None,
    from_stage: Annotated[str | None, typer.Option(
        "--from-stage", help="'extract': re-extract (all files, or the --only files) ignoring "
        "the cache. Later stages always rerun.")] = None,
    no_publish: Annotated[bool, typer.Option("--no-publish", help="Build and validate only")]
    = False,
    offline: Annotated[bool, typer.Option(help="Cached model calls only")] = False,
    no_embed: Annotated[bool, typer.Option("--no-embed", help="Skip embeddings")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Build a new dataset version, validate it, and publish it if validation passes."""
    from copilot_ingest.pipeline import RunOptions
    from copilot_ingest.pipeline import run as run_pipeline

    if from_stage not in (None, "extract"):
        typer.echo(f"--from-stage {from_stage}: only 'extract' is cached; every later stage "
                   "already reruns on each build")
        raise typer.Exit(1)
    code, report = run_pipeline(RunOptions(corpus=corpus, acl=acl, users=users,
                                           only=set(only) if only else None,
                                           from_stage=from_stage,
                                           publish=not no_publish, offline=offline,
                                           embed=not no_embed))
    if as_json:
        typer.echo(json.dumps({k: report.get(k) for k in ("run_id", "dataset_version",
                                                         "outcome", "report_path")}))
    else:
        _summary(report)
    raise typer.Exit(code)


def _summary(r: dict) -> None:
    """Print a short run summary: file outcomes, counts, review items, validation, errors."""
    files = r.get("files", [])
    kinds: dict[str, int] = {}
    for f in files:
        k = f["outcome"].split(":")[0]
        kinds[k] = kinds.get(k, 0) + 1
    c = r.get("counts", {})
    v = r.get("validation", [])
    failed = [x for x in v if not x["passed"] and x["severity"] == "error"]
    warned = [x for x in v if not x["passed"] and x["severity"] != "error"]
    review = r.get("review", [])
    rk: dict[str, int] = {}
    for i in review:
        rk[i["kind"]] = rk.get(i["kind"], 0) + 1
    typer.echo(f"run {r['run_id']}  dataset {r.get('dataset_version')}")
    typer.echo(f"files: {len(files)}  " + "  ".join(f"{k}: {n}" for k, n in sorted(kinds.items())))
    if c:
        typer.echo(f"passages: {c.get('passages')}  events: {c.get('events')}  "
                   f"assets: {c.get('assets')}  embeddings: {c.get('embeddings')}")
    typer.echo(f"review items: {len(review)} open"
               + (f" ({', '.join(f'{n} {k}' for k, n in sorted(rk.items()))})" if rk else ""))
    typer.echo(f"validation: {len(v) - len(failed) - len(warned)}/{len(v)} passed"
               + (f", {len(warned)} warnings" if warned else ""))
    for x in failed:
        typer.echo(f"  FAIL {x['name']}: {x['detail']}")
    for x in warned:
        typer.echo(f"  warn {x['name']}: {x['detail']}")
    for e in r.get("errors", [])[:5]:
        typer.echo(f"  error: {str(e)[:300]}")
    typer.echo(f"outcome: {r['outcome']}   report: {r.get('report_path')}")


@app.command()
def status() -> None:
    """Published version and versions available for rollback."""
    with connect() as conn:
        current = published_version(conn)
        row = conn.execute("SELECT published_at, run_id FROM control.published").fetchone()
        typer.echo(f"published: {current or '-'}"
                   + (f"  at {row[0]:%Y-%m-%d %H:%M}  run {row[1]}" if row else ""))
        typer.echo(f"available: {', '.join(dataset_versions(conn)) or '-'}")
        last = conn.execute("SELECT run_id, outcome, dataset_version FROM control.runs"
                            " ORDER BY started_at DESC LIMIT 5").fetchall()
        for run_id, outcome, version in last:
            typer.echo(f"  {run_id}  {outcome or 'running'}  {version or ''}")


@app.command()
def report(run_id: Annotated[str | None, typer.Option("--run")] = None,
           as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Print a run report (latest by default)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT report_path FROM control.runs WHERE (%s::text IS NULL OR run_id = %s)"
            " AND report_path IS NOT NULL ORDER BY started_at DESC LIMIT 1",
            (run_id, run_id)).fetchone()
    if not row:
        typer.echo("no report found")
        raise typer.Exit(1)
    path = Path(row[0])
    typer.echo((path.with_suffix(".json") if as_json else path).read_text())


@app.command()
def rollback(version: str) -> None:
    """Point serving at a retained earlier version."""
    from copilot_ingest.stages.publish import publish

    with connect() as conn:
        ok = conn.execute("SELECT 1 FROM control.runs WHERE dataset_version = %s"
                          " AND outcome = 'published'", (version,)).fetchone()
        if not ok:
            typer.echo(f"{version} was never published (it did not pass validation)")
            raise typer.Exit(1)
        publish(conn, version, f"rollback-{version}", validation_passed=True)
    typer.echo(f"serving now points at {version}")


@app.command()
def visible(user: Annotated[str, typer.Option()],
            doc: Annotated[str | None, typer.Option()] = None,
            search: Annotated[str | None, typer.Option()] = None) -> None:
    """Debug: what a user can see through the serving contract."""
    from copilot_ingest.acl import load_access_rules

    s = get_settings()
    groups = load_access_rules(s.acl_path, s.users_path).user_groups(user)
    with connect() as conn:
        if search:
            rows = conn.execute(
                "SELECT k.passage_id, p.heading_path, left(p.text_original, 120) FROM"
                " serving.keyword_search(%s, %s, 10) k JOIN serving.passages_for(%s) p"
                " USING (passage_id)", (groups, search, groups)).fetchall()
            for pid, hp, text in rows:
                typer.echo(f"{pid}  {' > '.join(hp)[:60]}\n    {text!r}")
            return
        rows = conn.execute(
            "SELECT d.title, o.path, (SELECT count(*) FROM serving.passages_for(%s) p"
            " WHERE p.doc_id = d.doc_id) FROM serving.documents_for(%s) d JOIN"
            " serving.document_origins o USING (doc_id)"
            " WHERE %s::text IS NULL OR o.path = %s ORDER BY o.path",
            (groups, groups, doc, doc)).fetchall()
        typer.echo(f"{user} ({', '.join(groups)}): {len(rows)} documents")
        for title, path, n in rows:
            typer.echo(f"  {path}  [{n} passages]  {title}")


@review_app.command("list")
def review_list(kind: Annotated[str | None, typer.Option()] = None,
                status_: Annotated[str, typer.Option("--status")] = "open") -> None:
    """Review items with a given status (open by default), optionally of one kind."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT item_id, kind, path, field, reason FROM control.review_items"
            " WHERE status = %s AND (%s::text IS NULL OR kind = %s) ORDER BY kind, path",
            (status_, kind, kind)).fetchall()
    for r in rows:
        typer.echo(f"{r[0]}  {r[1]:22} {r[2] or '-'}  {r[3] or ''}  {r[4] or ''}")


_HOW_TO_RESOLVE = {
    "marker_approval": '"approve", "reject", or {"approved": [...], "rejected": [...]}',
    "restricted_borderline": '"restrict" or "release"',
    "unknown_asset": 'a fleet asset ID, or "keep"',
    "unresolved_link": 'the correct case number, or "none"',
    "ocr_value_mismatch": 'the value as printed on the page image, or "withhold"',
    "metadata_unverified": "the revision (e.g. A) or the issue date as YYYY-MM-DD",
}


@review_app.command("show")
def review_show(item_id: str) -> None:
    """Source location, candidates, reason, and the resolution if there is one."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT i.item_id, i.kind, i.path, i.anchor, i.field, i.candidates, i.reason,"
            " i.status, i.first_run, i.last_run, r.value, r.note, r.resolved_by, r.resolved_at"
            " FROM control.review_items i LEFT JOIN control.resolutions r USING (item_id)"
            " WHERE i.item_id LIKE %s", (item_id + "%",)).fetchall()
        if len(rows) != 1:
            typer.echo(f"{len(rows)} items match {item_id!r}")
            raise typer.Exit(1)
        (iid, kind, path, anchor, fld, cand, reason, st, first, last,
         value, note, by, at) = rows[0]
        typer.echo(f"item:       {iid}\nkind:       {kind}\nstatus:     {st}"
                   f"  (first seen {first}, last seen {last})")
        typer.echo(f"source:     {path or '-'}  {json.dumps(anchor) if anchor else ''}")
        typer.echo(f"field:      {fld or '-'}\nreason:     {reason}")
        typer.echo(f"candidates: {json.dumps(cand, ensure_ascii=False)}")
        if cand and isinstance(cand, dict) and cand.get("page_image"):
            typer.echo(f"page image: {cand['page_image']}")
        version = published_version(conn)
        if anchor and anchor.get("passage_id") and version:
            row = conn.execute(f"SELECT text_original FROM {version}.passages"  # noqa: S608
                               " WHERE passage_id = %s", (anchor["passage_id"],)).fetchone()
            if row:
                typer.echo("passage:\n    " + row[0][:1200].replace("\n", "\n    "))
        if value is not None:
            typer.echo(f"resolution: {json.dumps(value, ensure_ascii=False)}"
                       f"  by {by or '-'} at {at:%Y-%m-%d %H:%M}"
                       + (f"  note: {note}" if note else ""))
        else:
            typer.echo(f"resolve:    copilot-ingest review resolve {iid[:12]} --value "
                       f"{_HOW_TO_RESOLVE.get(kind, 'VALUE')!r}")


@review_app.command("resolve")
def review_resolve(item_id: str,
                   value: Annotated[str, typer.Option(help="JSON or a plain string")],
                   note: Annotated[str | None, typer.Option()] = None,
                   by: Annotated[str | None, typer.Option(help="Reviewer name")] = None) -> None:
    """Record a resolution; applied on the next run."""
    from copilot_ingest.review import InvalidResolution, resolve

    with connect() as conn:
        try:
            full, applied = resolve(conn, item_id, value, note, by)
        except InvalidResolution as e:
            typer.echo(f"not resolved: {e}")
            raise typer.Exit(1) from e
        conn.commit()
    typer.echo(f"resolved {full}: {json.dumps(applied, ensure_ascii=False)}"
               "\napplied on the next run")


if __name__ == "__main__":
    app()
