"""Access grid (US4): reuses the 003 (answer API) grid test instead of re-implementing it. It
calls `GET /api/sources/{id}` for every user in users.json and every passage, and requires
200 or 403 exactly as `serving.can_see` says, and no page image on a partly hidden page."""
import re
import subprocess
import sys
import time

from copilot_ingest.settings import PROJECT_ROOT

GRID_TEST = "tests/api/test_sources.py::test_exhaustive_grid_matches_can_see"


def run_grid() -> dict:
    """Run the grid test in a pytest subprocess; returns pass, summary line and seconds, with the
    output tail only when it failed."""
    start = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", GRID_TEST],
        cwd=PROJECT_ROOT, capture_output=True, text=True)
    tail = (proc.stdout.strip().splitlines() or [""])[-1]
    passed = proc.returncode == 0 and re.search(r"\b1 passed\b", tail) is not None
    return {"test": GRID_TEST, "passed": passed, "skipped": "skipped" in tail,
            "summary": tail, "seconds": round(time.monotonic() - start, 1),
            "output": "" if passed else proc.stdout[-4000:] + proc.stderr[-2000:]}
