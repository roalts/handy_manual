"""Manual testing: uv run python -m copilot_answer ask --user u03 "question" """
import json
import sys

import typer

from copilot_answer.engine import build_engine
from copilot_answer.identity import load_identity
from copilot_answer.llm import session_spend_usd
from copilot_contracts import AskRequest

app = typer.Typer(add_completion=False)


@app.command()
def ask(question: str, user: str = typer.Option(..., "--user"),
        asset: str | None = typer.Option(None, "--asset"),
        offline: bool = typer.Option(False, help="Use cached model calls only.")) -> None:
    """Print the AnswerResponse JSON for a question asked as a test user."""
    engine = build_engine(offline=offline)
    resp = engine.answer(load_identity(user), AskRequest(question=question, asset_id=asset))
    print(resp.model_dump_json(indent=2))
    print(f"cost of this question: US${engine.last_meter.cost_usd:.4f}; engine spend so far: "
          f"US${session_spend_usd():.4f}", file=sys.stderr)


@app.command()
def spend() -> None:
    """Spend of the answer engine recorded in data/usage.jsonl."""
    print(json.dumps({"usd": round(session_spend_usd(), 4)}))


if __name__ == "__main__":
    app()
