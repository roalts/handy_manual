"""Fake MaintPro and Servio adapters: one JSON file per idempotency key, never a network call."""
import json
import os
import uuid
from pathlib import Path


class FakeOutbox:
    def __init__(self, root: Path):
        """Outbox folder, one subfolder per system."""
        self.root = Path(root)

    def path(self, system: str, key: str) -> Path:
        """File holding the record for `key` in the system's outbox."""
        return self.root / system / f"{key}.json"

    def read(self, system: str, key: str) -> dict | None:
        """Stored record for `key`, or None if none was written."""
        path = self.path(system, key)
        return json.loads(path.read_text()) if path.exists() else None

    def write_once(self, system: str, key: str, record: dict) -> dict:
        """Write the record unless the key already has one; return what is stored.

        The file appears atomically (hard link of a complete temp file), so a reader or a
        concurrent writer never sees a partial record and a second write never replaces it.
        """
        if (existing := self.read(system, key)) is not None:
            return existing
        folder = self.root / system
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f".{key}.{uuid.uuid4().hex}.tmp"
        tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        try:
            os.link(tmp, self.path(system, key))
        except FileExistsError:
            pass
        finally:
            tmp.unlink()
        return self.read(system, key)
