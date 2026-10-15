"""Scratch database and corpus copy for pipeline runs that must not touch the real dataset."""
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from copilot_ingest.settings import get_settings

SCRATCH_DB = "copilot_ingest_test"
CACHE_TABLES = ("cache.embeddings", "cache.model_calls")


@dataclass
class Scratch:
    root: Path
    corpus: Path
    acl: Path
    users: Path
    url: str


def _copy_cache(src_url: str, dst_url: str) -> None:
    """Copy model-call and embedding caches so scratch runs reuse what was already paid for."""
    with psycopg.connect(src_url) as src, psycopg.connect(dst_url) as dst:
        for conn in (src, dst):
            register_vector(conn)
        for table in CACHE_TABLES:
            cols = [r[0] for r in src.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = %s"
                " AND table_name = %s ORDER BY ordinal_position", tuple(table.split(".")))]
            rows = [tuple(Jsonb(v) if isinstance(v, dict | list) else v for v in r)
                    for r in src.execute(f"SELECT {', '.join(cols)} FROM {table}")]  # noqa: S608
            with dst.cursor() as cur:
                cur.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES"  # noqa: S608
                                f" ({', '.join(['%s'] * len(cols))}) ON CONFLICT DO NOTHING",
                                rows)
        dst.commit()


@pytest.fixture(scope="module")
def scratch(tmp_path_factory):
    real = get_settings()
    admin_url = "postgresql:///postgres"
    url = f"postgresql:///{SCRATCH_DB}"
    try:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)")
            admin.execute(f"CREATE DATABASE {SCRATCH_DB}")
    except psycopg.OperationalError as e:
        pytest.skip(f"cannot create scratch database: {e}")

    root = tmp_path_factory.mktemp("ingest")
    shutil.copytree(real.corpus_dir, root / "corpus")
    shutil.copy(real.acl_path, root / "permissions.json")
    shutil.copy(real.users_path, root / "users.json")
    (root / "data").mkdir()
    # extraction artifacts are content-addressed: share them so runs do not re-extract
    (root / "data" / "artifacts").symlink_to(real.data_dir / "artifacts")

    env = {"DATABASE_URL": url, "CORPUS_DIR": str(root / "corpus"),
           "DATA_DIR": str(root / "data"), "ACL_PATH": str(root / "permissions.json"),
           "USERS_PATH": str(root / "users.json")}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    get_settings.cache_clear()
    try:
        from copilot_ingest.db.repo import migrate

        migrate()
        _copy_cache(real.database_url, url)
        yield Scratch(root=root, corpus=root / "corpus", acl=root / "permissions.json",
                      users=root / "users.json", url=url)
        _copy_cache(url, real.database_url)  # keep anything newly embedded during the tests
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        get_settings.cache_clear()
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)")
