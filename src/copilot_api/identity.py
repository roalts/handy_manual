"""The trusted identity source: `users.json`, re-read on every call so changes apply at once."""
import json
from dataclasses import dataclass
from pathlib import Path

from copilot_contracts import Identity


@dataclass(frozen=True)
class User:
    user_id: str
    name: str
    title: str
    groups: frozenset[str]

    def identity(self) -> Identity:
        """The contract `Identity` passed to the answer engine and work order services."""
        return Identity(user_id=self.user_id, name=self.name, groups=self.groups)


class Directory:
    def __init__(self, path: Path) -> None:
        """`path` is users.json; nothing is read until a lookup."""
        self.path = path

    def _load(self) -> dict:
        """users.json, parsed afresh."""
        return json.loads(self.path.read_text(encoding="utf-8"))

    def users(self) -> list[User]:
        """Every user in users.json."""
        return [User(u["id"], u["name"], u.get("title", ""), frozenset(u.get("groups", ())))
                for u in self._load().get("users", [])]

    def user(self, user_id: str) -> User | None:
        """The user with this ID, or None."""
        return next((u for u in self.users() if u.user_id == user_id), None)

    def groups(self) -> dict[str, str]:
        """Group ID -> plain description."""
        return dict(self._load().get("groups", {}))
