"""Reference data the checks are measured against, read only through `serving.*` (contracts
README rule 2), in read-only transactions.

The system under test is reached only through the HTTP API (FR-001). This module reads what the
answers are judged against: the restricted procedures and their markers (FR-005), the procedure
steps for the similarity rule, and, to place a missed fact in a stage (FR-007), which passages
a user can see. Markers and restricted text never leave the harness: reports name a procedure
and a marker count, not the content.
"""
import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Protocol

import psycopg

from copilot_ingest.stages.restricted import step_lines


@dataclass(frozen=True)
class Procedure:
    name: str
    title: str
    doc_id: str
    alternatives: tuple[frozenset[str], ...]

    def satisfied_by(self, groups: frozenset[str]) -> bool:
        """`groups` holds every group of at least one access alternative."""
        return any(alt <= groups for alt in self.alternatives)


class Reference(Protocol):
    def dataset_version(self) -> str:
        """Dataset version the serving schema holds."""
        ...
    def procedures(self) -> list[Procedure]:
        """Restricted procedures with their access alternatives."""
        ...
    def markers(self) -> dict[str, list[str]]:
        """Procedure name -> its markers."""
        ...
    def procedure_steps(self) -> dict[str, list[str]]:
        """Procedure name -> its step lines."""
        ...
    def visible_texts(self, groups: frozenset[str]) -> dict[str, str]:
        """passage_id -> text of every passage `groups` can see."""
        ...


class PgReference:
    def __init__(self, database_url: str, users_path: Path) -> None:
        """Reads users.json once: each user's groups and the full group catalog."""
        self.database_url = database_url
        users = json.loads(users_path.read_text())
        self.users = {u["id"]: frozenset(u["groups"]) for u in users["users"]}
        self.catalog = sorted(users["groups"])
        self._visible: dict[frozenset[str], dict[str, str]] = {}

    def _rows(self, sql: str, params=()) -> list[tuple]:
        """Run one query on its own read-only connection."""
        with psycopg.connect(self.database_url) as conn:
            conn.read_only = True
            return conn.execute(sql, params).fetchall()

    def dataset_version(self) -> str:
        """Dataset version from `serving.dataset_info()`, queried on every call."""
        return self._rows("SELECT dataset_version FROM serving.dataset_info()")[0][0]

    @cached_property
    def _procedures(self) -> list[Procedure]:
        """One per procedure name, its access alternatives in `alt_no` order; queried once."""
        by_name: dict[str, list] = {}
        for name, title, doc_id, groups in self._rows(
                "SELECT name, title, doc_id, required_groups FROM serving.restricted_procedures"
                " ORDER BY name, alt_no"):
            by_name.setdefault(name, []).append((title, doc_id, frozenset(groups)))
        return [Procedure(n, alts[0][0], alts[0][1], tuple(a[2] for a in alts))
                for n, alts in sorted(by_name.items())]

    def procedures(self) -> list[Procedure]:
        """Restricted procedures, read once."""
        return self._procedures

    def markers(self) -> dict[str, list[str]]:
        """Both `approved` and `proposed` markers: proposed ones apply until reviewed."""
        out: dict[str, list[str]] = {}
        for proc, marker in self._rows(
                "SELECT procedure, marker FROM serving.restricted_markers ORDER BY 1, 2"):
            out.setdefault(proc, []).append(marker)
        return out

    @cached_property
    def _steps(self) -> dict[str, list[str]]:
        """Numbered step lines (ingestion's `step_lines`) of each procedure's own passages and
        of every passage tagged with it."""
        out: dict[str, list[str]] = {}
        for p in self._procedures:
            rows = self._rows(
                "SELECT text_original, text_en FROM serving.passages_for(%s)"
                " WHERE doc_id = %s OR %s = ANY(restricted_tags) ORDER BY passage_id",
                (self.catalog, p.doc_id, p.name))
            lines: list[str] = []
            for original, english in rows:
                for text in (original, english):
                    for s in step_lines(text or ""):
                        if s not in lines:
                            lines.append(s)
            out[p.name] = lines
        return out

    def procedure_steps(self) -> dict[str, list[str]]:
        """Step lines per procedure, read once."""
        return self._steps

    def visible_texts(self, groups: frozenset[str]) -> dict[str, str]:
        """passage_id -> original and English text `groups` can see, cached per group set."""
        if groups not in self._visible:
            self._visible[groups] = {
                pid: f"{orig}\n{en or ''}" for pid, orig, en in self._rows(
                    "SELECT passage_id, text_original, text_en FROM serving.passages_for(%s)",
                    (sorted(groups),))}
        return self._visible[groups]
