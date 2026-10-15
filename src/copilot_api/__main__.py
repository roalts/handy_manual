"""Run the answer API: `uv run python -m copilot_api [--host 127.0.0.1] [--port 8000]`."""
import argparse
import logging

import uvicorn

from copilot_api import build_app


def main() -> None:
    """Parse --host and --port, then serve the fully wired app with uvicorn."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run(build_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
