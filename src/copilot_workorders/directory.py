"""Other users' groups from users.json, the trusted identity source, re-read on every lookup."""
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DirectoryUser:
    user_id: str
    name: str
    groups: frozenset[str]


class UsersFile:
    def __init__(self, path: Path):
        """Users file at `path`; nothing is read until a lookup."""
        self.path = Path(path)

    def users(self) -> list[DirectoryUser]:
        """Every user in the file, re-read on each call."""
        data = json.loads(self.path.read_text())
        return [DirectoryUser(u["id"], u["name"], frozenset(u["groups"])) for u in data["users"]]
