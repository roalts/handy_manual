"""Structure-aware chunking (research.md R12).

Rules:
- A numbered procedure is one unit: from the heading of its first step through its last step,
  with the document's safety warnings that precede it. Never split without a parent.
- Units above PROCEDURE_MAX tokens become a parent passage plus children (one per subsection,
  or windows of about three steps).
- Other sections stay whole up to SECTION_MAX tokens, else split at block boundaries; split
  tables repeat their header row; long prose uses sentence windows with overlap.
- One passage per case record, chat thread, and email message.
"""
import re
from functools import lru_cache

import tiktoken
from lingua import Language, LanguageDetectorBuilder

from copilot_ingest.ids import passage_id_for
from copilot_ingest.models import Anchor, Block, ExtractResult, Passage
from copilot_ingest.stages.normalize import identifiers

VERSION = "chunk-1"
SECTION_MAX = 500
PROCEDURE_MAX = 800
MESSAGE_MAX = 1200
WINDOW_OVERLAP = 50
MIN_STEPS = 3
_SAFETY_HEADING = re.compile(r"safety|sicherheit|veiligheid|säkerhet", re.I)
_TOC_HEADING = re.compile(r"(table of )?contents|inhalt(sverzeichnis)?|inhoud(sopgave)?|"
                          r"innehåll(sförteckning)?", re.I)

_LANGS = {Language.ENGLISH: "en", Language.GERMAN: "de", Language.DUTCH: "nl",
          Language.SWEDISH: "sv"}


@lru_cache
def _enc():
    """The o200k_base tokenizer, loaded once."""
    return tiktoken.get_encoding("o200k_base")


@lru_cache
def _detector():
    """Language detector limited to EN/DE/NL/SV, built once."""
    return LanguageDetectorBuilder.from_languages(*_LANGS).build()


def tokens(text: str) -> int:
    """Token count of the text."""
    return len(_enc().encode(text))


def detect_lang(text: str) -> str | None:
    """ISO 639-1 code of the text's language, or None if under 30 characters or undetected."""
    if len(text) < 30:
        return None
    lang = _detector().detect_language_of(text)
    return _LANGS.get(lang) if lang else None


# --- procedure detection ------------------------------------------------------------------

def _step_number(b: Block):
    """Step number (int, or dotted string) of a procedure step or numbered list item, else None."""
    if b.type == "procedure_step" or (b.type == "list_item" and b.fields
                                       and b.fields.get("number") is not None):
        return (b.fields or {}).get("number")
    return None


def _continues(prev, cur) -> bool:
    """Whether step `cur` follows `prev`: the next integer, or a dotted number in the same
    top-level step."""
    if isinstance(prev, int) and isinstance(cur, int):
        return cur == prev + 1
    if isinstance(prev, str) and isinstance(cur, str):
        return prev.split(".")[0] == cur.split(".")[0]
    return False


def find_procedures(blocks: list[Block]) -> list[tuple[int, int]]:
    """Return (start, end) block index ranges, end inclusive, for numbered procedures.

    A run of steps never crosses a top-level chapter.
    """
    runs: list[list[int]] = []
    for i, b in enumerate(blocks):
        n = _step_number(b)
        if n is None:
            continue
        prev = blocks[runs[-1][-1]] if runs else None
        if prev is not None and _continues(_step_number(prev), n) \
                and prev.heading_path[:1] == b.heading_path[:1]:
            runs[-1].append(i)
        else:
            runs.append([i])
    ranges = []
    for run in runs:
        if len(run) < MIN_STEPS:
            continue
        first, last = run[0], run[-1]
        # start at the heading that owns all steps (the parent when they span subsections)
        common = _common_prefix([blocks[i].heading_path for i in run])
        start = first
        for j in range(first, -1, -1):
            if blocks[j].type == "heading" and blocks[j].heading_path == common:
                start = j
                break
            if blocks[j].heading_path[:len(common)] != common:
                break
        end = last
        while end + 1 < len(blocks) and blocks[end + 1].type != "heading" \
                and blocks[end + 1].heading_path == blocks[last].heading_path \
                and blocks[end + 1].type in ("warning", "paragraph", "table"):
            end += 1
        ranges.append((start, end))
    merged: list[tuple[int, int]] = []
    for s, e in sorted(ranges):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
        else:
            merged.append((s, e))
    return merged


def _common_prefix(paths: list[list[str]]) -> list[str]:
    """Longest heading path shared by all paths."""
    if not paths:
        return []
    out = []
    for parts in zip(*paths, strict=False):
        if all(p == parts[0] for p in parts):
            out.append(parts[0])
        else:
            break
    return out


# --- passage assembly -----------------------------------------------------------------------

def _block_text(b: Block) -> str:
    """Text a block contributes to a passage."""
    if b.type == "heading":
        return b.text
    return b.text


def _anchor_for(blocks: list[Block]) -> Anchor:
    """The first block's anchor, widened to a page range and with the table cleared unless all
    blocks share one table."""
    first = blocks[0].anchor
    pages = [b.anchor.page for b in blocks if b.anchor.page is not None]
    data = first.model_dump()
    if pages and max(pages) != min(pages):
        data["page"], data["page_end"] = min(pages), max(pages)
    tables = {b.anchor.table for b in blocks if b.anchor.table is not None}
    if len(tables) != 1:
        data["table"] = None
    return Anchor(**data)


class Chunker:
    def __init__(self, result: ExtractResult, doc_id: str, default_lang: str | None = None):
        """`default_lang` is used for passages whose language cannot be detected."""
        self.r = result
        self.doc_id = doc_id
        self.default_lang = default_lang
        self.passages: list[Passage] = []

    def _make(self, blocks: list[Block], text: str, role="standard", parent=None,
              heading_path=None, anchor: Anchor | None = None) -> Passage:
        """Build a passage with its identifiers and language, append it, and return it."""
        anchor = anchor or _anchor_for(blocks)
        hp = heading_path if heading_path is not None else (blocks[0].heading_path or [])
        ids = identifiers(text + " " + " ".join(hp))
        p = Passage(
            passage_id=passage_id_for(self.doc_id, anchor.key() + role, text),
            doc_id=self.doc_id, role=role, parent_passage_id=parent, anchor=anchor,
            heading_path=list(hp), block_types=sorted({b.type for b in blocks}),
            lang=detect_lang(text) or self.default_lang, text_original=text,
            fault_codes=ids["fault_codes"], part_numbers=ids["part_numbers"],
            asset_ids=ids["asset_ids"], serials=ids["serials"],
            case_numbers=ids["case_numbers"], models=ids["models"],
            fingerprint=self.r.fingerprint, extractor_version=self.r.extractor_version,
        )
        self.passages.append(p)
        return p

    def _join(self, blocks: list[Block]) -> str:
        """Block texts, one per line, skipping empty blocks."""
        return "\n".join(_block_text(b) for b in blocks if b.text)

    # sections ---------------------------------------------------------------------------
    def _section(self, blocks: list[Block]):
        """One passage if the section fits SECTION_MAX, else block groups under the section
        heading; oversized tables and paragraphs are split on their own."""
        if not blocks:
            return
        text = self._join(blocks)
        if tokens(text) <= SECTION_MAX:
            self._make(blocks, text)
            return
        heading = [b for b in blocks[:1] if b.type == "heading"]
        body = blocks[len(heading):]
        prefix = heading[0].text + "\n" if heading else ""
        group: list[Block] = []
        for b in body:
            if b.type == "table" and tokens(b.text) > SECTION_MAX:
                self._flush(group, prefix)
                group = []
                self._table(b, prefix)
                continue
            if b.type == "paragraph" and tokens(b.text) > SECTION_MAX:
                self._flush(group, prefix)
                group = []
                self._windows(b, prefix)
                continue
            if group and tokens(prefix + self._join(group + [b])) > SECTION_MAX:
                self._flush(group, prefix)
                group = []
            group.append(b)
        self._flush(group, prefix)

    def _flush(self, group: list[Block], prefix: str):
        """Make a passage from a non-empty group."""
        if group:
            self._make(group, prefix + self._join(group))

    def _table(self, b: Block, prefix: str):
        """Split a large table into row groups, each repeating the header row."""
        header = " | ".join(b.header or [])
        rows = b.rows or []
        chunk: list[str] = []
        for row in rows:
            line = " | ".join(row)
            if chunk and tokens(prefix + header + "\n" + "\n".join(chunk + [line])) > SECTION_MAX:
                self._make([b], prefix + header + "\n" + "\n".join(chunk))
                chunk = []
            chunk.append(line)
        if chunk:
            self._make([b], prefix + header + "\n" + "\n".join(chunk))

    def _windows(self, b: Block, prefix: str):
        """Split long text into sentence windows, carrying up to WINDOW_OVERLAP tokens of
        trailing sentences into the next window."""
        sentences = re.split(r"(?<=[.!?])\s+", b.text)
        window: list[str] = []
        for s in sentences:
            if window and tokens(prefix + " ".join(window + [s])) > SECTION_MAX:
                self._make([b], prefix + " ".join(window))
                overlap: list[str] = []
                while window and tokens(" ".join([window[-1], *overlap])) <= WINDOW_OVERLAP:
                    overlap.insert(0, window.pop())
                window = overlap
            window.append(s)
        if window:
            self._make([b], prefix + " ".join(window))

    # procedures -------------------------------------------------------------------------
    def _procedure(self, blocks: list[Block], safety: list[Block]):
        """One passage with the safety warnings prepended, or above PROCEDURE_MAX a parent plus
        child passages."""
        body = self._join(blocks)
        safety_text = "\n".join(b.text for b in safety)
        text = (safety_text + "\n" + body).strip() if safety_text else body
        hp = blocks[0].heading_path
        if tokens(text) <= PROCEDURE_MAX:
            self._make(safety + blocks, text, heading_path=hp, anchor=_anchor_for(blocks))
            return
        parent = self._make(safety + blocks, text, role="parent", heading_path=hp,
                            anchor=_anchor_for(blocks))
        for child in self._child_groups(blocks):
            hp = child[0].heading_path
            # the child's own heading is its first block; prefix only the enclosing sections
            context = hp[:-1] if child[0].type == "heading" else hp
            prefix = " > ".join(context) + "\n" if context else ""
            self._make(child, prefix + self._join(child), role="child",
                       parent=parent.passage_id, heading_path=hp)

    def _child_groups(self, blocks: list[Block]) -> list[list[Block]]:
        """One child per subsection; subsections with many steps become ~3-step windows."""
        groups: list[list[Block]] = []
        for b in blocks:
            if not groups or (b.type == "heading" and groups[-1]):
                groups.append([])
            groups[-1].append(b)
        out: list[list[Block]] = []
        for g in groups:
            if tokens(self._join(g)) <= SECTION_MAX:
                out.append(g)
                continue
            lead = [b for b in g if _step_number(b) is None and g.index(b) < 2]
            steps = g[len(lead):]
            for i in range(0, len(steps), 3):
                out.append(lead + steps[i:i + 3])
        return [g for g in out if any(b.type != "heading" for b in g)]

    # entry point ------------------------------------------------------------------------
    def run(self) -> list[Passage]:
        """Passages for the document: one per message or record, else procedures and sections."""
        # tables of contents only repeat headings and page numbers
        blocks = [b for b in self.r.blocks if b.text.strip()
                  and not (b.heading_path and _TOC_HEADING.fullmatch(b.heading_path[0].strip()))]
        if not blocks:
            return []
        if all(b.type in ("message", "record") for b in blocks):
            for b in blocks:
                if tokens(b.text) <= MESSAGE_MAX:
                    self._make([b], b.text)
                else:
                    parent = self._make([b], b.text, role="parent")
                    before = len(self.passages)
                    self._windows(b, "")
                    for p in self.passages[before:]:
                        p.role, p.parent_passage_id = "child", parent.passage_id
                        p.passage_id = passage_id_for(self.doc_id, p.anchor.key() + "child" +
                                                      str(self.passages.index(p)),
                                                      p.text_original)
            return self.passages

        procedures = find_procedures(blocks)
        in_proc = {i: (s, e) for s, e in procedures for i in range(s, e + 1)}
        i = 0
        section: list[Block] = []
        while i < len(blocks):
            if i in in_proc:
                self._section(section)
                section = []
                s, e = in_proc[i]
                safety = [b for b in blocks[:s] if b.type == "warning" and (
                    any(_SAFETY_HEADING.search(h) for h in b.heading_path)
                    or b.heading_path[:1] == blocks[s].heading_path[:1])]
                self._procedure(blocks[s:e + 1], safety)
                i = e + 1
                continue
            b = blocks[i]
            if b.type == "heading" and section:
                self._section(section)
                section = []
            section.append(b)
            i += 1
        self._section(section)
        return self.passages


def chunk(result: ExtractResult, doc_id: str, default_lang: str | None = None) -> list[Passage]:
    """Passages for one extracted document."""
    return Chunker(result, doc_id, default_lang).run()
