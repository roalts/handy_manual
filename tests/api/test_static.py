"""Static files and client routes (http-api.md, Static files and client routes)."""
import pytest


@pytest.mark.parametrize("path", ["/", "/index.html", "/sources/p_79e8df3857393da815e28cdf",
                                  "/work-orders/wo_123"])
def test_index_routes(harness, path):
    r = harness.client().get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<html" in r.text.lower()


def test_assets(harness):
    js = harness.client().get("/assets/app.js")
    assert js.status_code == 200
    assert js.headers["content-type"].startswith("text/javascript")


@pytest.mark.parametrize("path", [
    "/dev/mock_api.py", "/dev/fixtures/sources.json", "/styles.css", "/js/app.js",
    "/assets/../dev/mock_api.py", "/assets/%2e%2e%2fdev%2fmock_api.py", "/web/index.html",
    "/assets/missing.js", "/assets/app.py", "/../users.json", "/users.json", "/.env",
])
def test_nothing_else_is_served(harness, path):
    r = harness.client().get(path)
    assert r.status_code == 404
    assert "mock" not in r.text.lower() or r.json() == {"error": "not_found"}
