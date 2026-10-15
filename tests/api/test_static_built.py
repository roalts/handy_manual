"""A built client served from WEB_DIR, and gzip on static files (http-api.md, Static files and
client routes)."""
import gzip
import re

import pytest

from copilot_ingest.settings import PROJECT_ROOT

REACT_DIST = PROJECT_ROOT / "web-react" / "dist"
TYPES = {"app-1a2b.js": "text/javascript", "index-3c4d.css": "text/css",
         "logo.svg": "image/svg+xml", "icon.png": "image/png", "font.woff2": "font/woff2"}
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64


@pytest.fixture
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets" / "nested").mkdir(parents=True)
    (root / "index.html").write_text(
        '<!doctype html><html><head><script type="module" src="/assets/app-1a2b.js"></script>'
        "</head><body>" + "built client " * 200 + "</body></html>")
    for name in TYPES:
        data = PNG if name.endswith(".png") else ("x" * 4000).encode()
        (root / "assets" / name).write_bytes(data)
    (root / "assets" / "nested" / "chunk.js").write_text("export const x = 1;" * 100)
    (root / "assets" / "app.js.map").write_text("{}")
    (root / "secret.txt").write_text("outside assets")
    (tmp_path / "outside.js").write_text("outside dist")
    (root / "assets" / "link.js").symlink_to(tmp_path / "outside.js")
    return root


@pytest.fixture
def built(make_harness, dist):
    return make_harness(web_dir=dist).client()


@pytest.mark.parametrize("path", ["/", "/index.html", "/sources/p_79e8df3857393da815e28cdf",
                                  "/work-orders/wo_123", "/work-orders/wo_123/edit"])
def test_built_client_routes_return_index(built, path):
    r = built.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "built client" in r.text


@pytest.mark.parametrize(("name", "ctype"), sorted(TYPES.items()))
def test_assets_have_the_right_content_type(built, name, ctype):
    r = built.get(f"/assets/{name}")
    assert r.status_code == 200
    assert r.headers["content-type"].split(";")[0] == ctype


def test_nested_asset(built):
    r = built.get("/assets/nested/chunk.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")


@pytest.mark.parametrize("path", [
    "/assets/", "/assets", "/assets/nested", "/assets/missing.js", "/assets/app.js.map",
    "/assets/link.js", "/assets/../secret.txt", "/assets/%2e%2e/secret.txt",
    "/assets/%2e%2e/%2e%2e/outside.js", "/assets/..%2f..%2foutside.js", "/secret.txt",
    "/styles.css", "/js/app.js", "/dev/mock_api.py", "/users.json", "/.env", "/favicon.ico",
    "/anything/else",
])
def test_nothing_outside_is_served(built, path):
    r = built.get(path)
    assert r.status_code == 404
    assert r.json() == {"error": "not_found"}


def test_gzip_with_vary(built):
    r = built.get("/assets/app-1a2b.js", headers={"Accept-Encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip"
    assert r.headers["vary"] == "Accept-Encoding"
    assert r.text == "x" * 4000
    raw = built.get("/", headers={"Accept-Encoding": "gzip, br"})
    assert raw.headers["content-encoding"] == "gzip"


@pytest.mark.parametrize("accept", ["identity", "br", "gzip;q=0", ""])
def test_no_gzip_unless_accepted(built, accept):
    r = built.get("/assets/index-3c4d.css", headers={"Accept-Encoding": accept})
    assert "content-encoding" not in r.headers
    assert r.headers["vary"] == "Accept-Encoding"
    assert r.content == ("x" * 4000).encode()


def test_png_is_not_gzipped(built):
    r = built.get("/assets/icon.png", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in r.headers
    assert r.content == PNG


def test_gzip_body_is_valid(make_harness, dist):
    """Check the bytes on the wire, without the client's automatic decoding."""
    c = make_harness(web_dir=dist).client()
    with c.stream("GET", "/assets/nested/chunk.js", headers={"Accept-Encoding": "gzip"}) as r:
        wire = b"".join(r.iter_raw())
    assert gzip.decompress(wire) == ("export const x = 1;" * 100).encode()
    assert len(wire) < 200


def test_changed_file_is_served_fresh(make_harness, dist):
    c = make_harness(web_dir=dist).client()
    assert "built client" in c.get("/").text
    (dist / "index.html").write_text("<html>rebuilt and much longer than before</html>")
    assert "rebuilt" in c.get("/").text


def test_relative_web_dir_is_from_project_root(monkeypatch, tmp_path):
    from copilot_api.config import load_config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WEB_DIR", "elsewhere/dist")
    assert load_config().web_dir == PROJECT_ROOT / "elsewhere" / "dist"
    monkeypatch.delenv("WEB_DIR")
    assert load_config().web_dir == REACT_DIST


def test_api_is_unchanged_in_built_mode(make_harness, dist):
    h = make_harness(web_dir=dist)
    r = h.client().get("/api/health")
    assert r.json()["status"] == "ok"
    assert r.headers["cache-control"] == "no-store"
    assert h.client().get("/api/nope").json() == {"error": "not_found"}


@pytest.mark.skipif(not (REACT_DIST / "index.html").is_file(), reason="web-react not built")
def test_real_react_build(make_harness):
    """Every file of web-react/dist/assets and every asset index.html references is served."""
    c = make_harness(web_dir=REACT_DIST).client()
    index = c.get("/", headers={"Accept-Encoding": "gzip"})
    assert index.status_code == 200 and index.headers["content-encoding"] == "gzip"
    refs = set(re.findall(r'(?:src|href)="(/assets/[^"]+)"', index.text))
    assert refs
    files = {f"/assets/{p.relative_to(REACT_DIST / 'assets').as_posix()}"
             for p in (REACT_DIST / "assets").rglob("*") if p.is_file()}
    assert refs <= files
    for path in sorted(files):
        r = c.get(path, headers={"Accept-Encoding": "gzip"})
        assert r.status_code == 200, path
        suffix = path.rsplit(".", 1)[-1]
        expected = {"js": "text/javascript", "css": "text/css", "svg": "image/svg+xml",
                    "png": "image/png", "woff2": "font/woff2"}[suffix]
        assert r.headers["content-type"].split(";")[0] == expected, path
        assert r.headers["vary"] == "Accept-Encoding"
    assert c.get("/sources/p_1").text == index.text
