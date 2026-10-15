import pytest

from copilot_ingest.acl import load_access_rules
from copilot_ingest.settings import get_settings


@pytest.fixture
def db():
    import psycopg

    try:
        conn = psycopg.connect(get_settings().database_url, autocommit=True)
    except psycopg.OperationalError as e:
        pytest.skip(f"database not available: {e}")
    if conn.execute("SELECT to_regnamespace('serving')").fetchone()[0] is None:
        pytest.skip("no published dataset; run `copilot-ingest run` first")
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def rules():
    s = get_settings()
    return load_access_rules(s.acl_path, s.users_path)
