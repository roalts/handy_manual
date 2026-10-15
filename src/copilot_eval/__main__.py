"""Run the evaluation: `uv run python -m copilot_eval run [options]`.

By default it starts its own API instance (real engine and serving, scratch schema for drafts
and audit) on a free port, never 8000, and stops it at the end.

Exit codes (FR-008): 0 no release-blocking failure; 1 a disclosure, access-grid or citation
failure; 2 infrastructure error (API unavailable, contract broken): no score.
"""
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from copilot_eval import cases as case_mod
from copilot_eval import report
from copilot_eval.categorize import Failure
from copilot_eval.client import Api, InfrastructureError
from copilot_eval.grid import run_grid
from copilot_eval.reference import PgReference
from copilot_eval.runner import run
from copilot_eval.server import FORBIDDEN_PORTS
from copilot_ingest.settings import PROJECT_ROOT, get_settings


def _free_port(start: int = 8020) -> int:
    """First port from `start` with nothing listening, never the user's dev server port."""
    for port in range(start, start + 100):
        if port in FORBIDDEN_PORTS:
            continue
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise InfrastructureError("no free port")


def _server_env(budget_usd: float, fresh: bool) -> dict[str, str]:
    """Server environment with the spend cap; ANSWER_FRESH only from `fresh`, never inherited."""
    env = {**os.environ, "ANSWER_BUDGET_USD": str(budget_usd)}
    env.pop("ANSWER_FRESH", None)
    if fresh:
        env["ANSWER_FRESH"] = "1"
    return env


def _start_server(port: int, meter: Path, budget_usd: float, fresh: bool) -> subprocess.Popen:
    """Start the harness's API server and wait up to 180 s for a healthy `/api/health`."""
    env = _server_env(budget_usd, fresh)
    proc = subprocess.Popen([sys.executable, "-m", "copilot_eval.server", "--port", str(port),
                             "--meter", str(meter)], cwd=PROJECT_ROOT, env=env)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise InfrastructureError(f"API server exited with {proc.returncode}")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=2).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(1)
    proc.terminate()
    raise InfrastructureError("API server did not start within 180 s")


def _stop_server(proc: subprocess.Popen) -> None:
    """SIGINT so the server drops its scratch schema; killed if it hasn't exited after 30 s."""
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()


def _configured_prompts() -> list[str]:
    """Prompt versions in the answer engine's config (its `PROMPT_*` names)."""
    from copilot_answer import config

    return [getattr(config, n) for n in sorted(dir(config))
            if n.startswith("PROMPT_") and isinstance(getattr(config, n), str)]


def _embedder():
    """Embedding function with ingestion's embedding model and dimensions; vectors come from
    ingestion's cache, and only uncached texts are sent to the hosted API."""
    from copilot_ingest.providers.cache import get_provider

    s = get_settings()
    provider = get_provider()
    return lambda texts: provider.embed(s.embedding_model, texts, s.embedding_dims)


def compare(a: Path, b: Path) -> int:
    """Differences in verdicts between two runs' `.json` files; exit 1 if any."""
    va, vb = json.loads(a.read_text()), json.loads(b.read_text())
    diffs = [f"{k}: {va[k]} vs {vb[k]}" for k in ("dataset_version", "prompts", "grid")
             if va.get(k) != vb.get(k)]
    for cid in sorted(set(va["cases"]) | set(vb["cases"])):
        ca, cb = va["cases"].get(cid), vb["cases"].get(cid)
        if ca != cb:
            diffs.append(f"{cid}: {ca} vs {cb}")
    print("\n".join(diffs) if diffs else "same verdicts")
    return 1 if diffs else 0


def main(argv: list[str] | None = None) -> int:
    """Run or compare; a run writes the report and its `.json` verdicts. Returns the exit code."""
    ap = argparse.ArgumentParser(prog="copilot_eval", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the evaluation and write a dated report")
    r.add_argument("--base-url", help="use a running API instead of starting one "
                   "(never the user's port 8000)")
    r.add_argument("--port", type=int, help="port for the harness's own API instance")
    r.add_argument("--only", help="comma-separated case IDs")
    r.add_argument("--no-grid", action="store_true", help="skip the access grid")
    r.add_argument("--budget", type=float, default=0.40,
                   help="engine spend cap for the harness's own API instance, US$ (a model "
                   "call past it is a 503, which stops the run)")
    r.add_argument("--fresh", action="store_true",
                   help="no model-cache reads in the harness's own API instance "
                   "(ANSWER_FRESH=1 for that instance only; not with --base-url)")
    r.add_argument("--dump", type=Path,
                   help="write each response with its fetched sources here (for triage)")
    r.add_argument("--reports-dir", type=Path, default=PROJECT_ROOT / "data/reports")
    c = sub.add_parser("compare", help="compare the verdicts of two runs (SC-004)")
    c.add_argument("a", type=Path)
    c.add_argument("b", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "compare":
        return compare(args.a, args.b)

    s = get_settings()
    all_cases = case_mod.load(PROJECT_ROOT / "eval")
    cases = [c for c in all_cases if not args.only or c.id in args.only.split(",")]
    ref = PgReference(s.database_url, s.users_path)
    proc = None
    meter = Path(tempfile.mkdtemp(prefix="copilot_eval_")) / "meter.jsonl"
    command = "uv run python -m copilot_eval " + " ".join(argv or sys.argv[1:])
    try:
        if args.base_url and args.fresh:
            raise InfrastructureError("--fresh needs the harness's own API instance")
        if args.base_url:
            if any(f":{p}" in args.base_url for p in FORBIDDEN_PORTS):
                raise InfrastructureError("port 8000 is the user's dev server; not used")
            base = args.base_url
        else:
            port = args.port or _free_port()
            if port in FORBIDDEN_PORTS:
                raise InfrastructureError("port 8000 is the user's dev server; not used")
            proc = _start_server(port, meter, args.budget, args.fresh)
            base = f"http://127.0.0.1:{port}"
        result = run(cases, Api(base), ref, ref.users, _embedder())
    except InfrastructureError as e:
        print(f"infrastructure error, no score: {e}", file=sys.stderr)
        return 2
    finally:
        if proc:
            _stop_server(proc)

    prompts_used: set[str] = set()
    if meter.exists():
        by_answer = {}
        for line in meter.read_text().splitlines():
            row = json.loads(line)
            by_answer[row["answer_id"]] = row["calls"]
        for res in result.results:
            calls = by_answer.get(res.response.answer_id)
            if calls is not None:
                res.calls = calls
                res.cost_usd = sum(c["cost_usd"] for c in calls if not c["cached"])
                prompts_used |= {c["prompt_version"] for c in calls}
    if not args.no_grid:
        result.grid = run_grid()
        if not result.grid["passed"]:
            result.extra_failures.append(Failure(
                "grid", "grid", "policy", True,
                f"access grid failed: {result.grid['summary']}", result.grid["output"][:300]))
    exit_code = 1 if result.blocking else 0
    meta = {"exit_code": exit_code, "api": "own instance at " + base if proc else base,
            "prompts_used": sorted(prompts_used), "prompts_configured": _configured_prompts(),
            "command": command, "fresh": args.fresh}
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    path = report.write(result, meta, args.reports_dir)
    verdicts = {"dataset_version": result.dataset_version, "prompts": meta["prompts_used"],
                "cases": {res.case.id: {
                    "status": res.response.status,
                    "facts": {f.fact.fact: f.hit for f in res.facts},
                    "exemptions": sorted(
                        f"{x['procedure']}|{x['unit']}|{x['rule']}|{x['step']}|"
                        f"{x['passage_id']}" for x in res.disclosure_stats.get("exemptions", [])),
                    "failures": sorted(f"{f.check}|{f.category}|{f.detail}"
                                       for f in res.failures)} for res in result.results},
                "grid": result.grid and result.grid["passed"], "exit_code": exit_code}
    path.with_suffix(".json").write_text(json.dumps(verdicts, indent=1, sort_keys=True))
    if args.dump:
        args.dump.write_text(json.dumps({res.case.id: {
            "user_id": res.case.user_id, "response": res.response.model_dump(mode="json"),
            "sources": res.sources, "disclosure_stats": res.disclosure_stats,
            "failures": [f"{f.check}|{f.category}|{f.detail}" for f in res.failures]}
            for res in result.results}, indent=1, default=str))
    shown = path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path
    print(f"report: {shown}")
    print(f"release-blocking failures: {len(result.blocking)}; exit code {exit_code}")
    return exit_code


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    sys.exit(main())
