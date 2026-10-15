from typing import Any, Protocol


class ProviderUnavailable(RuntimeError):
    """Raised when a hosted call cannot be made (no key, no credits, offline cache miss)."""


class Provider(Protocol):
    name: str

    def complete_json(self, model: str, prompt: str, schema: dict[str, Any],
                      prompt_version: str) -> dict[str, Any]:
        """JSON object matching `schema` for a text prompt."""
        ...

    def transcribe_image(self, model: str, image_png: bytes, prompt: str,
                         schema: dict[str, Any], prompt_version: str) -> dict[str, Any]:
        """JSON object matching `schema` read from a PNG image."""
        ...

    def embed(self, model: str, texts: list[str], dims: int) -> list[list[float]]:
        """One `dims`-length vector per text, in input order."""
        ...
