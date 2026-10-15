import base64
import json
import time
from typing import Any

import openai

from copilot_ingest.providers.base import ProviderUnavailable
from copilot_ingest.settings import get_settings

_RETRYABLE = (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError,
              openai.InternalServerError)


def _log_usage(model: str, prompt_version: str, usage) -> None:
    """One line per paid call in data/usage.jsonl, so spend can be reported."""
    if usage is None:
        return
    details = getattr(usage, "output_tokens_details", None)
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": model,
           "prompt_version": prompt_version, "input_tokens": usage.input_tokens,
           "output_tokens": usage.output_tokens,
           "reasoning_tokens": getattr(details, "reasoning_tokens", None)}
    path = get_settings().data_dir / "usage.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")


class OpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        """Raises ProviderUnavailable without an API key. SDK retries are off; `_call` retries."""
        key = get_settings().openai_api_key
        if not key:
            raise ProviderUnavailable("OPENAI_API_KEY is not set")
        self.client = openai.OpenAI(api_key=key, max_retries=0)

    def _call(self, fn, *args, **kwargs):
        """Call `fn` with up to 5 attempts and exponential backoff on transient errors. Auth
        failures, exhausted credits and repeated failures raise ProviderUnavailable."""
        for attempt in range(5):
            try:
                return fn(*args, **kwargs)
            except openai.RateLimitError as e:
                # Exhausted credits are reported as a rate-limit error; retrying cannot help.
                if "insufficient_quota" in str(e) or "credits" in str(e):
                    raise ProviderUnavailable(f"OpenAI account has no credits: {e}") from e
                time.sleep(2**attempt)
            except _RETRYABLE:
                time.sleep(2**attempt)
            except openai.AuthenticationError as e:
                raise ProviderUnavailable(f"OpenAI authentication failed: {e}") from e
        raise ProviderUnavailable("OpenAI call failed after retries")

    def _structured(self, model: str, content: list[dict[str, Any]],
                    schema: dict[str, Any], prompt_version: str) -> dict[str, Any]:
        """JSON output constrained to `schema`; logs usage, and an incomplete response raises
        ProviderUnavailable."""
        resp = self._call(
            self.client.responses.create,
            model=model,
            input=[{"role": "user", "content": content}],
            reasoning={"effort": "low"},
            text={"format": {"type": "json_schema", "name": "result", "strict": True,
                             "schema": schema}},
        )
        _log_usage(model, prompt_version, resp.usage)
        if resp.status == "incomplete":
            raise ProviderUnavailable(f"response incomplete: {resp.incomplete_details}")
        return json.loads(resp.output_text)

    def complete_json(self, model: str, prompt: str, schema: dict[str, Any],
                      prompt_version: str) -> dict[str, Any]:
        """Structured completion for a text prompt."""
        return self._structured(model, [{"type": "input_text", "text": prompt}], schema,
                                prompt_version)

    def transcribe_image(self, model: str, image_png: bytes, prompt: str,
                         schema: dict[str, Any], prompt_version: str) -> dict[str, Any]:
        """Structured reading of a PNG page image, sent inline at high detail."""
        data_url = "data:image/png;base64," + base64.b64encode(image_png).decode()
        return self._structured(model, [{"type": "input_text", "text": prompt},
                                        {"type": "input_image", "image_url": data_url,
                                         "detail": "high"}], schema, prompt_version)

    def embed(self, model: str, texts: list[str], dims: int) -> list[list[float]]:
        """Vectors in input order, requested 256 texts at a time."""
        out: list[list[float]] = []
        for i in range(0, len(texts), 256):
            resp = self._call(self.client.embeddings.create, model=model,
                              input=texts[i:i + 256], dimensions=dims)
            out.extend(d.embedding for d in resp.data)
        return out
