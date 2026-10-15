"""Identity from the trusted identity source (users.json). Used by the CLI and tests; the API
builds `Identity` from its signed session the same way."""
import json

from copilot_contracts import Identity
from copilot_ingest.settings import get_settings


def load_identity(user_id: str) -> Identity:
    """Identity of a user from users.json; KeyError for an unknown user."""
    users = json.loads(get_settings().users_path.read_text())["users"]
    for u in users:
        if u["id"] == user_id:
            return Identity(user_id=u["id"], name=u["name"], groups=frozenset(u["groups"]))
    raise KeyError(f"unknown user {user_id}")
