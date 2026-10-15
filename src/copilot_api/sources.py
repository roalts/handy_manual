"""Citation viewer data, read only through `serving.*` (contracts README rule 2).

Each call runs in one read-only REPEATABLE READ transaction, so a request sees one published
dataset version even if a publish happens meanwhile.
"""
import queue
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import psycopg
from psycopg import IsolationLevel

from copilot_answer.build import locator as citation_locator

MAX_WIDTH = 1600
PDF_DPI = 150

_PASSAGE = ("SELECT p.passage_id, p.doc_id, p.anchor, p.heading_path, p.lang, p.text_original,"
            " p.text_en, p.ocr, p.page_image, p.possibly_stale"
            " FROM serving.passages_for(%s) p WHERE p.passage_id = %s")
_DOCUMENT = ("SELECT d.doc_id, d.title, d.doc_type, d.revision, d.issue_date, d.status"
             " FROM serving.documents_for(%s) d WHERE d.doc_id = %s")
_ALL_GROUPS = ("SELECT unnest(required_groups) FROM serving.document_origins"
               " UNION SELECT unnest(required_groups) FROM serving.restricted_procedures")
_EXISTS = "SELECT EXISTS (SELECT 1 FROM serving.passages_for(%s) p WHERE p.passage_id = %s)"


@dataclass(frozen=True)
class ImageRef:
    kind: Literal["scan", "pdf"]
    path: Path
    page: int


@dataclass
class SourceResult:
    outcome: Literal["shown", "not_visible", "not_found"]
    dataset_version: str
    view: dict | None = None
    image: ImageRef | None = None


class SourceStore:
    def __init__(self, database_url: str, corpus_dir: Path, data_dir: Path,
                 known_groups: Callable[[], Iterable[str]]) -> None:
        """`known_groups` lists directory groups, used to tell hidden passages from missing ones."""
        self.database_url = database_url
        self.corpus_dir = corpus_dir
        self.data_dir = data_dir
        self.known_groups = known_groups
        self._idle: queue.LifoQueue[psycopg.Connection] = queue.LifoQueue()
        self._images: OrderedDict[ImageRef, bytes] = OrderedDict()
        self._images_lock = threading.Lock()

    # ------------------------------------------------------------------ plumbing

    def _connect(self) -> psycopg.Connection:
        """A new connection whose explicit transactions are read-only REPEATABLE READ."""
        conn = psycopg.connect(self.database_url, autocommit=True)
        conn.isolation_level = IsolationLevel.REPEATABLE_READ
        conn.read_only = True
        return conn

    def _run(self, fn):
        """fn(conn) inside one read-only transaction on a pooled connection."""
        for attempt in (1, 2):
            try:
                conn = self._idle.get_nowait()
            except queue.Empty:
                conn = self._connect()
            try:
                with conn.transaction():
                    result = fn(conn)
            except psycopg.OperationalError:
                conn.close()
                if attempt == 2:
                    raise
                continue
            except BaseException:
                conn.close()
                raise
            self._idle.put(conn)
            return result

    @staticmethod
    def _version(conn) -> str:
        """The dataset version served, as seen by `conn`'s transaction."""
        return conn.execute("SELECT dataset_version FROM serving.dataset_info()").fetchone()[0]

    # ------------------------------------------------------------------ queries

    def dataset_version(self) -> str:
        """The dataset version currently served."""
        return self._run(self._version)

    def visible(self, groups: frozenset[str], ids: Iterable[str]) -> set[str]:
        """The passage IDs among `ids` that `groups` may see."""
        ids = list(ids)
        if not ids:
            return set()
        return self._run(lambda c: {r[0] for r in c.execute(
            "SELECT id FROM unnest(%s::text[]) id WHERE serving.can_see('passage', id, %s)",
            (ids, sorted(groups))).fetchall()})

    def source(self, groups: frozenset[str], passage_id: str) -> SourceResult:
        """The citation view for a passage, or why it can't be shown."""
        return self._run(lambda c: self._source(c, sorted(groups), passage_id))

    def _source(self, conn, g: list[str], passage_id: str) -> SourceResult:
        """A passage `g` can't see is not_visible if any known group could, else not_found.
        The superseding document and the page image are given only when visible to `g`."""
        version = self._version(conn)
        row = conn.execute(_PASSAGE, (g, passage_id)).fetchone()
        doc = conn.execute(_DOCUMENT, (g, row[1])).fetchone() if row else None
        if row is None or doc is None:
            every = set(self.known_groups()) | {r[0] for r in conn.execute(_ALL_GROUPS)}
            exists = conn.execute(_EXISTS, (sorted(every), passage_id)).fetchone()[0]
            return SourceResult("not_visible" if exists else "not_found", version)
        pid, doc_id, anchor, heading_path, lang, text_original, text_en, ocr, page_image, \
            stale = row
        _, title, doc_type, revision, issue_date, status = doc
        anchor = anchor or {}
        relations = conn.execute(
            "SELECT from_doc, to_doc, relation FROM serving.document_relations"
            " WHERE (relation = 'supersedes' AND to_doc = %s)"
            "    OR (relation = 'possibly_stale_vs' AND from_doc = %s)",
            (doc_id, doc_id)).fetchall()
        newer = next((f for f, _, rel in relations if rel == "supersedes"), None)
        if newer and not conn.execute("SELECT serving.can_see('document', %s, %s)",
                                      (newer, g)).fetchone()[0]:
            newer = None
        page = anchor.get("page")
        image = None
        if page is not None and conn.execute(
                "SELECT serving.page_fully_visible(%s, %s, %s)", (g, doc_id, page)).fetchone()[0]:
            image = self._image_ref(conn, doc_id, int(page), page_image)
        loc = citation_locator(SimpleNamespace(
            passage=SimpleNamespace(anchor=anchor, heading_path=heading_path or []),
            doc=SimpleNamespace(doc_type=doc_type, title=title)))
        view = {
            "passage_id": pid, "doc_id": doc_id, "title": title, "doc_type": doc_type,
            "revision": revision, "issue_date": issue_date.isoformat() if issue_date else None,
            "status": status, "superseded_by": newer, "locator": loc, "lang": lang,
            "text_original": text_original, "text_en": text_en,
            "page": int(page) if page is not None else None,
            "page_image_url": f"/api/sources/{pid}/page.png" if image else None,
            "ocr": ocr != "none",
            "possibly_stale": bool(stale) or any(r[2] == "possibly_stale_vs" for r in relations),
        }
        return SourceResult("shown", version, view, image)

    def _image_ref(self, conn, doc_id: str, page: int, page_image: str | None) -> ImageRef | None:
        """The page's scan image if any, else the document's first source PDF; None if missing."""
        if page_image:
            path = self.data_dir / page_image
            return ImageRef("scan", path, page) if path.is_file() else None
        for (rel,) in conn.execute("SELECT path FROM serving.document_origins WHERE doc_id = %s"
                                   " ORDER BY path", (doc_id,)).fetchall():
            path = self.corpus_dir / rel
            if path.suffix.lower() == ".pdf" and path.is_file():
                return ImageRef("pdf", path, page)
        return None

    # ------------------------------------------------------------------ images

    def render(self, ref: ImageRef) -> bytes | None:
        """The page as PNG, kept in a 32-page LRU cache; None if the PDF lacks the page."""
        with self._images_lock:
            if ref in self._images:
                self._images.move_to_end(ref)
                return self._images[ref]
        data = _render(ref)
        if data is not None:
            with self._images_lock:
                self._images[ref] = data
                while len(self._images) > 32:
                    self._images.popitem(last=False)
        return data


def _render(ref: ImageRef) -> bytes | None:
    """PNG at most MAX_WIDTH pixels wide (PDF pages at PDF_DPI); None for a page out of range."""
    import pymupdf

    with pymupdf.open(ref.path) as doc:
        if ref.kind == "scan":
            page = doc[0]
            pixels = pymupdf.Pixmap(str(ref.path)).width
            zoom = min(pixels, MAX_WIDTH) / page.rect.width
        else:
            if not 1 <= ref.page <= doc.page_count:
                return None
            page = doc[ref.page - 1]
            zoom = min(PDF_DPI / 72, MAX_WIDTH / page.rect.width)
        return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")
