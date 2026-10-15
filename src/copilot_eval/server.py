"""The harness's own API instance: the real engine and serving, work orders and audit in a scratch
schema and a temporary outbox (removed on exit), as `tests/api/serve_scratch.py` does.

    uv run python -m copilot_eval.server --port 8020 --meter data/tmp/meter.jsonl

The only addition is a meter: after each answer the engine's model calls (prompt version,
cached or not, cost) are appended to `--meter` under the answer's ID, so the report can give
cost per question. The harness itself still talks to this server over HTTP only.
"""
import argparse
import json
import logging
import tempfile
import threading
import uuid
from pathlib import Path

import psycopg
import uvicorn

from copilot_answer import build_engine
from copilot_api import Deps, create_app
from copilot_api.config import load_config
from copilot_api.engines import EnginePool
from copilot_api.identity import Directory
from copilot_api.session import Sessions
from copilot_api.sources import SourceStore
from copilot_workorders import build_services, migrate

FORBIDDEN_PORTS = {8000}
"""The user's own dev server."""


class MeteredEngine:
    def __init__(self, inner, meter_path: Path, lock: threading.Lock) -> None:
        """Wrap `inner`; `lock` serializes appends to the meter file."""
        self.inner = inner
        self.meter_path = meter_path
        self.lock = lock

    def answer(self, identity, request):
        """Inner engine's answer; its model calls are appended to the meter under the answer ID."""
        resp = self.inner.answer(identity, request)
        calls = [{"prompt_version": c.prompt_version, "model": c.model, "cached": c.cached,
                  "cost_usd": c.cost_usd, "seconds": round(c.seconds, 3)}
                 for c in self.inner.last_meter.calls]
        with self.lock, self.meter_path.open("a") as f:
            f.write(json.dumps({"answer_id": resp.answer_id, "calls": calls}) + "\n")
        return resp


def main() -> None:
    """Serve on a scratch schema and temporary outbox, dropping the schema on exit; refuses the
    user's dev server port."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--meter", type=Path, required=True)
    args = ap.parse_args()
    if args.port in FORBIDDEN_PORTS:
        raise SystemExit(f"port {args.port} is reserved for the user's dev server")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    schema = f"wo_eval_{uuid.uuid4().hex[:8]}"
    lock = threading.Lock()
    args.meter.parent.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(cfg.database_url, autocommit=True) as db, \
            tempfile.TemporaryDirectory() as outbox:
        migrate(db, schema=schema)
        try:
            wo, audit = build_services(cfg.database_url, schema=schema,
                                       users_path=cfg.users_path, outbox_dir=Path(outbox))
            directory = Directory(cfg.users_path)
            sources = SourceStore(cfg.database_url, cfg.corpus_dir, cfg.data_dir,
                                  known_groups=lambda: directory.groups().keys())
            app = create_app(Deps(
                config=cfg, directory=directory,
                sessions=Sessions(cfg.session_secret, cfg.session_max_age),
                # One engine: `last_meter` is per engine, and the harness asks one at a time.
                engines=EnginePool(lambda: MeteredEngine(build_engine(), args.meter, lock), 1),
                sources=sources, work_orders=wo, audit=audit))
            print(f"scratch schema {schema}", flush=True)
            uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
        finally:
            db.execute(f"DROP SCHEMA {schema} CASCADE")
            print(f"dropped scratch schema {schema}", flush=True)


if __name__ == "__main__":
    main()
