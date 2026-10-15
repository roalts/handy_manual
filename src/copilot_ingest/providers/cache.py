import json
from typing import Any

from psycopg.types.json import Jsonb

from copilot_ingest.db.repo import connect
from copilot_ingest.ids import sha256_bytes
from copilot_ingest.providers.base import Provider, ProviderUnavailable

EMBED_BATCH = 256


class CachedProvider:
    """Caches every hosted call by (provider, model, prompt version, input hash).

    Reruns are identical because outputs are read back from the cache, not because the model is
    deterministic. In offline mode a cache miss raises ProviderUnavailable.
    """

    def __init__(self, inner: Provider | None, offline: bool = False) -> None:
        """Without an inner provider the cache is always offline."""
        self.inner = inner
        self.offline = offline or inner is None
        self.name = inner.name if inner else "offline"

    def _key(self, model: str, prompt_version: str, input_hash: str) -> str:
        """Cache key; bumping the prompt version forces fresh calls."""
        return sha256_bytes(f"{self.name}|{model}|{prompt_version}|{input_hash}".encode())

    def _cached_call(self, model: str, prompt_version: str, payload: bytes, call) -> dict:
        """Cached output for this payload, else run `call` and store its result."""
        input_hash = sha256_bytes(payload)
        key = self._key(model, prompt_version, input_hash)
        with connect() as conn:
            row = conn.execute("SELECT output FROM cache.model_calls WHERE key = %s",
                               (key,)).fetchone()
            if row:
                return row[0]
            if self.offline:
                raise ProviderUnavailable(f"cache miss in offline mode ({prompt_version})")
            out = call()
            conn.execute(
                "INSERT INTO cache.model_calls (key, provider, model, prompt_version, input_hash,"
                " output) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (key) DO NOTHING",
                (key, self.name, model, prompt_version, input_hash, Jsonb(out)),
            )
            conn.commit()
            return out

    def complete_json(self, model: str, prompt: str, schema: dict[str, Any],
                      prompt_version: str) -> dict[str, Any]:
        """Cached structured completion; the key covers both prompt and schema."""
        payload = (prompt + json.dumps(schema, sort_keys=True)).encode()
        return self._cached_call(model, prompt_version, payload,
                                 lambda: self.inner.complete_json(model, prompt, schema,
                                                                  prompt_version))

    def transcribe_image(self, model: str, image_png: bytes, prompt: str,
                         schema: dict[str, Any], prompt_version: str) -> dict[str, Any]:
        """Cached image transcription; the key covers image bytes, prompt and schema."""
        payload = image_png + prompt.encode() + json.dumps(schema, sort_keys=True).encode()
        return self._cached_call(model, prompt_version, payload,
                                 lambda: self.inner.transcribe_image(model, image_png, prompt,
                                                                     schema, prompt_version))

    def embed(self, model: str, texts: list[str], dims: int) -> list[list[float]]:
        """Vectors in input order, cached per text, model and dims; only misses are sent."""
        hashes = [sha256_bytes(t.encode()) for t in texts]
        found: dict[str, list[float]] = {}
        with connect() as conn:
            rows = conn.execute(
                "SELECT text_hash, embedding FROM cache.embeddings"
                " WHERE model = %s AND dims = %s AND text_hash = ANY(%s)",
                (model, dims, hashes),
            ).fetchall()
            found = {h: e.to_list() if hasattr(e, "to_list") else list(e) for h, e in rows}
            missing = [i for i, h in enumerate(hashes) if h not in found]
            if missing and self.offline:
                raise ProviderUnavailable(f"{len(missing)} embeddings not cached (offline)")
            # Commit per batch so a failure mid-run keeps the vectors already paid for.
            for start in range(0, len(missing), EMBED_BATCH):
                batch = missing[start:start + EMBED_BATCH]
                vectors = self.inner.embed(model, [texts[i] for i in batch], dims)
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO cache.embeddings (text_hash, model, dims, embedding)"
                        " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        [(hashes[i], model, dims, v)
                         for i, v in zip(batch, vectors, strict=True)],
                    )
                conn.commit()
                for i, v in zip(batch, vectors, strict=True):
                    found[hashes[i]] = v
        return [found[h] for h in hashes]


def get_provider(offline: bool = False) -> CachedProvider:
    """OpenAI behind the cache; falls back to cache-only when no API key is set."""
    if offline:
        return CachedProvider(None, offline=True)
    try:
        from copilot_ingest.providers.openai_provider import OpenAIProvider

        return CachedProvider(OpenAIProvider())
    except ProviderUnavailable:
        return CachedProvider(None, offline=True)
