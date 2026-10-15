import json
from dataclasses import dataclass
from pathlib import Path


class AclConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AccessRules:
    """The authoritative access rules: document path -> required groups, plus users and groups."""

    documents: dict[str, list[str]]
    source_systems: dict[str, str]
    groups: dict[str, str]
    users: dict[str, list[str]]
    titles: dict[str, str]

    def required_groups(self, path: str) -> list[str] | None:
        """None means the document has no access rule (it must be quarantined)."""
        return self.documents.get(path)

    def unknown_groups(self, path: str) -> list[str]:
        """Groups the document requires that are not defined in the users file."""
        return [g for g in self.documents.get(path, []) if g not in self.groups]

    def user_groups(self, user_id: str) -> list[str]:
        """Groups a user belongs to; raises KeyError for an unknown user."""
        if user_id not in self.users:
            raise KeyError(f"unknown user {user_id}")
        return self.users[user_id]


def load_access_rules(acl_path: Path, users_path: Path, corpus_prefix: str = "corpus/"
                      ) -> AccessRules:
    """Read the permissions and users files. Document paths lose `corpus_prefix` so they match
    corpus-relative paths; undefined user groups or malformed rules raise AclConfigError."""
    perms = json.loads(acl_path.read_text())
    users = json.loads(users_path.read_text())
    groups = users["groups"]
    user_groups = {u["id"]: list(u["groups"]) for u in users["users"]}
    for uid, gs in user_groups.items():
        bad = [g for g in gs if g not in groups]
        if bad:
            raise AclConfigError(f"user {uid} belongs to undefined groups {bad}")
    docs: dict[str, list[str]] = {}
    systems: dict[str, str] = {}
    titles: dict[str, str] = {}
    for path, rule in perms["documents"].items():
        rel = path[len(corpus_prefix):] if path.startswith(corpus_prefix) else path
        if not isinstance(rule.get("required_groups"), list):
            raise AclConfigError(f"{path}: required_groups must be a list")
        docs[rel] = sorted(rule["required_groups"])
        systems[rel] = rule.get("source_system", "unknown")
        if rule.get("title"):
            titles[rel] = rule["title"]
    return AccessRules(documents=docs, source_systems=systems, groups=groups, users=user_groups,
                       titles=titles)


def can_see(required: list[str], user_groups: list[str]) -> bool:
    """True if the user has every required group (an empty requirement is visible to all)."""
    return set(required) <= set(user_groups)
