"""Serve the real API for manual walkthroughs without leaving rows in `app` or files in
`data/outbox`: work orders and audit go to a scratch schema and a temporary outbox, both removed
on exit. The answer engine is the real one (hosted model calls cost money).

    uv run python tests/api/serve_scratch.py [--port 8000]
"""
import argparse
import logging
import tempfile
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    schema = f"wo_walk_{uuid.uuid4().hex[:8]}"
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
                engines=EnginePool(build_engine, cfg.engine_pool), sources=sources,
                work_orders=wo, audit=audit))
            print(f"scratch schema {schema}, outbox {outbox}")
            uvicorn.run(app, host="127.0.0.1", port=args.port)
        finally:
            rows = db.execute(f"SELECT kind, outcome, count(*) FROM {schema}.audit_events"
                              " GROUP BY 1, 2 ORDER BY 1, 2").fetchall()
            print("audit events:", rows)
            print("outbox files:", sorted(p.name for p in Path(outbox).rglob("*.json")))
            db.execute(f"DROP SCHEMA {schema} CASCADE")


if __name__ == "__main__":
    main()
