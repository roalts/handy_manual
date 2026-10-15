"""Email (.eml and printed-to-PDF threads), Teams channel exports, Salesforce case exports."""
import email
import json
import re
from email import policy

import pymupdf
from bs4 import BeautifulSoup

from copilot_ingest.models import Anchor, Block, ExtractResult, PageCoverage

VERSION = "messages-1"

_FROM = r"From|Von|Van|Från"
_LABELS = {
    "from": ("From", "Von", "Van", "Från"),
    "sent": ("Sent", "Verzonden", "Gesendet", "Skickat", "Date", "Datum"),
    "to": ("To", "Aan", "An", "Till"),
    "cc": ("Cc", "CC"),
    "subject": ("Subject", "Onderwerp", "Betreff", "Ämne"),
    "attachments": ("Attachments", "Bijlagen", "Anlagen", "Bilagor"),
}
_LABEL_TO_KEY = {lab.lower(): key for key, labs in _LABELS.items() for lab in labs}
_HDR_LINE = re.compile(r"^\s*(" + "|".join(re.escape(lab) for lab in _LABEL_TO_KEY) +
                       r")\s*:\s*(.*)$", re.I)
_START = re.compile(r"^\s*(" + _FROM + r")\s*:", re.I)
_ORIGINAL = re.compile(r"^\s*-{2,}\s*(Original Message|Forwarded message|Oorspronkelijk bericht"
                       r"|Ursprüngliche Nachricht).*-{2,}\s*$", re.I)


def split_thread(text: str) -> list[dict]:
    """Split a reply chain into messages, newest first, as they appear in the text."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    messages: list[dict] = []
    cur = {"headers": {}, "body": []}
    i = 0
    while i < len(lines):
        line = lines[i]
        if _ORIGINAL.match(line):
            i += 1
            continue
        if _START.match(line):
            if cur["body"] or cur["headers"]:
                messages.append(cur)
            cur = {"headers": {}, "body": []}
            while i < len(lines):
                m = _HDR_LINE.match(lines[i])
                if not m:
                    break
                key = _LABEL_TO_KEY[m.group(1).lower()]
                value = m.group(2).strip()
                if not value and i + 1 < len(lines) and not _HDR_LINE.match(lines[i + 1]):
                    i += 1
                    value = lines[i].strip()
                cur["headers"].setdefault(key, value)
                i += 1
            continue
        cur["body"].append(line.lstrip("> ").rstrip() if line.startswith(">") else line.rstrip())
        i += 1
    if cur["body"] or cur["headers"]:
        messages.append(cur)
    out = []
    for m in messages:
        body = re.sub(r"\n{3,}", "\n\n", "\n".join(m["body"])).strip()
        if body or m["headers"]:
            out.append({"headers": m["headers"], "body": body})
    return out


def _message_blocks(msgs: list[dict], thread_subject: str | None, page_of=None) -> list[Block]:
    """One message block per newest-first message; ids and positions count up from the oldest.
    `page_of(message)` supplies the anchor page when given."""
    blocks = []
    total = len(msgs)
    for n, m in enumerate(msgs):
        h = m["headers"]
        mid = f"msg-{total - n:02d}"  # oldest message is msg-01
        header_txt = "; ".join(f"{k}: {v}" for k, v in h.items() if v and k != "attachments")
        text = (header_txt + "\n\n" + m["body"]).strip()
        blocks.append(Block(type="message", text=text,
                            anchor=Anchor(message_id=mid, page=page_of(m) if page_of else None,
                                          section_path=[thread_subject] if thread_subject else []),
                            fields={**h, "position": total - n}))
    return blocks


def extract_eml(path, rel_path: str, fingerprint: str) -> ExtractResult:
    """Split the body (plain preferred over HTML) into the reply chain. The envelope headers
    fill the top message, or a new header-only one if the body is empty or opens with a From:."""
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    part = msg.get_body(preferencelist=("plain", "html"))
    body = part.get_content() if part else ""
    if part is not None and part.get_content_type() == "text/html":
        body = BeautifulSoup(body, "lxml").get_text("\n")
    subject = msg["Subject"]
    top = {"from": msg["From"], "sent": msg["Date"], "to": msg["To"], "cc": msg["Cc"],
           "subject": subject}
    msgs = split_thread(body)
    if msgs and not msgs[0]["headers"]:
        msgs[0]["headers"] = {k: v for k, v in top.items() if v}
    else:
        msgs.insert(0, {"headers": {k: v for k, v in top.items() if v}, "body": ""})
    attachments = [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]
    blocks = _message_blocks(msgs, subject)
    return ExtractResult(path=rel_path, fingerprint=fingerprint, extractor="eml",
                         extractor_version=VERSION, title=subject, blocks=blocks,
                         pages=[PageCoverage(page=1, status="text", chars=len(body))],
                         flags={"attachments": attachments, "message_id": msg["Message-ID"]})


def extract_pdf_thread(path, rel_path: str, fingerprint: str) -> ExtractResult:
    """Email thread printed to PDF. Messages without headers are dropped; the subject is taken
    from the oldest message."""
    doc = pymupdf.open(str(path))
    page_texts = [p.get_text() for p in doc]
    full = "\n".join(page_texts)
    offsets, pos = [], 0
    for t in page_texts:
        offsets.append(pos)
        pos += len(t) + 1
    # drop the repeated page-top name line printed by the mail client
    first_lines = [t.strip().split("\n", 1)[0] for t in page_texts if t.strip()]
    banner = first_lines[0] if first_lines and first_lines.count(first_lines[0]) > 1 else None
    if banner:
        full = "\n".join(ln for ln in full.split("\n") if ln.strip() != banner)
    msgs = split_thread(full)
    msgs = [m for m in msgs if m["headers"]]
    subject = msgs[-1]["headers"].get("subject") if msgs else None

    def page_of(m):
        """First page containing the start of the message body, or None."""
        snippet = m["body"][:60]
        for i, t in enumerate(page_texts):
            if snippet and snippet[:40] in t:
                return i + 1
        return None

    blocks = _message_blocks(msgs, subject, page_of)
    pages = [PageCoverage(page=i + 1, status="text" if len(t.strip()) > 25 else "blank",
                          chars=len(t)) for i, t in enumerate(page_texts)]
    return ExtractResult(path=rel_path, fingerprint=fingerprint, extractor="pdf_thread",
                         extractor_version=VERSION, title=subject, blocks=blocks, pages=pages)


def _html_text(content: str) -> str:
    """Plain text of an HTML fragment; None or empty gives an empty string."""
    return BeautifulSoup(content or "", "lxml").get_text(" ", strip=True)


def extract_teams(path, rel_path: str, fingerprint: str) -> ExtractResult:
    """One message block per channel thread (root plus replies, oldest first). Replies whose
    parent is missing are kept as their own threads; skipped messages are counted in flags."""
    data = json.loads(path.read_text())
    channel = data.get("channel", {})
    channel_name = channel.get("displayName") if isinstance(channel, dict) else str(channel)
    msgs = data["value"]
    by_id = {m["id"]: m for m in msgs}
    roots = [m for m in msgs if not m.get("replyToId")]
    replies: dict[str, list] = {}
    for m in msgs:
        if m.get("replyToId"):
            replies.setdefault(m["replyToId"], []).append(m)
    flags = {"deleted": 0, "edited": 0, "system": 0, "orphan_replies": 0}
    blocks: list[Block] = []

    def render(m) -> str | None:
        """One chat line, or None for deleted and system messages; updates the flag counts."""
        if m.get("deletedDateTime"):
            flags["deleted"] += 1
            return None
        if m.get("messageType") != "message":
            flags["system"] += 1
            return None
        user = ((m.get("from") or {}).get("user") or {}).get("displayName") or "unknown"
        edited = " (edited)" if m.get("lastEditedDateTime") else ""
        if edited:
            flags["edited"] += 1
        return f"[{m['createdDateTime'][:16].replace('T', ' ')}] {user}{edited}: " \
               f"{_html_text(m['body']['content'])}"

    for parent_id in replies:
        if parent_id not in by_id:
            flags["orphan_replies"] += len(replies[parent_id])
            roots.extend(replies[parent_id])
    for root in sorted(roots, key=lambda m: m["createdDateTime"]):
        lines = [render(root)]
        thread = sorted(replies.get(root["id"], []), key=lambda m: m["createdDateTime"])
        lines += [render(r) for r in thread]
        lines = [ln for ln in lines if ln]
        if not lines:
            continue
        participants = sorted({((m.get("from") or {}).get("user") or {}).get("displayName")
                               or "unknown" for m in [root, *thread]})
        attachments = [a.get("name") for m in [root, *thread] for a in m.get("attachments") or []
                       if a.get("name")]
        blocks.append(Block(type="message", text="\n".join(lines),
                            anchor=Anchor(message_id=root["id"],
                                          section_path=[channel_name] if channel_name else []),
                            fields={"thread_start": root["createdDateTime"],
                                    "replies": len(thread), "participants": participants,
                                    "attachments": attachments}))
    chars = sum(len(b.text) for b in blocks)
    return ExtractResult(path=rel_path, fingerprint=fingerprint, extractor="teams",
                         extractor_version=VERSION, title=f"Teams: {channel_name}",
                         blocks=blocks, pages=[PageCoverage(page=1, status="text", chars=chars)],
                         flags=flags)


def _sf_children(value) -> list[dict]:
    """Child records of a Salesforce relationship, given either as `{"records": [...]}` or a
    plain list."""
    if not value:
        return []
    if isinstance(value, dict):
        return value.get("records") or []
    return list(value)


def _name(value) -> str | None:
    """`Name` of a related Salesforce object, or the value itself if it is not an object."""
    return value.get("Name") if isinstance(value, dict) else value


def extract_salesforce(path, rel_path: str, fingerprint: str) -> ExtractResult:
    """One record block per support case (fields, comments and emails as text) plus the
    structured case in `records`."""
    data = json.loads(path.read_text())
    recs = data["records"] if isinstance(data, dict) else data
    blocks, records = [], []
    for r in recs:
        comments = sorted(_sf_children(r.get("CaseComments")), key=lambda c: c["CreatedDate"])
        emails = sorted(_sf_children(r.get("EmailMessages")),
                        key=lambda e: e.get("MessageDate") or e.get("CreatedDate") or "")
        asset = _name(r.get("Asset__r"))
        rec = {
            "case_number": r["CaseNumber"], "subject": r.get("Subject"), "status": r.get("Status"),
            "priority": r.get("Priority"), "origin": r.get("Origin"),
            "created": r.get("CreatedDate"), "closed": r.get("ClosedDate"),
            "account": _name(r.get("Account")), "asset": asset,
            "model": r.get("Equipment_Model__c"), "serial": r.get("Serial_Number__c"),
            "site": r.get("Site__c"), "fault_code": r.get("Fault_Code__c"),
            "description": r.get("Description"), "resolution": r.get("Resolution__c"),
            "parts_used": r.get("Parts_Used__c"), "owner": _name(r.get("Owner")),
            "comments": [{"date": c.get("CreatedDate"), "by": _name(c.get("CreatedBy")),
                          "body": c.get("CommentBody")} for c in comments],
            "emails": [{"date": e.get("MessageDate") or e.get("CreatedDate"),
                        "from": e.get("FromAddress") or e.get("FromName"),
                        "subject": e.get("Subject"),
                        "body": e.get("TextBody") or _html_text(e.get("HtmlBody"))}
                       for e in emails],
        }
        records.append(rec)
        parts = [f"Case {rec['case_number']} ({rec['status']}, {rec['priority']}): "
                 f"{rec['subject']}",
                 f"Asset {asset} | {rec['model']} | serial {rec['serial']} | site {rec['site']}"
                 f" | fault {rec['fault_code'] or '-'}",
                 f"Opened {rec['created']}"
                 + (f", closed {rec['closed']}" if rec["closed"] else ""),
                 f"Description: {rec['description'] or '-'}"]
        if rec["resolution"]:
            parts.append(f"Resolution: {rec['resolution']}")
        if rec["parts_used"]:
            parts.append(f"Parts used: {rec['parts_used']}")
        parts += [f"Comment {c['date']} {c['by']}: {c['body']}" for c in rec["comments"]]
        parts += [f"Email {e['date']} {e['from']} - {e['subject']}: {e['body']}"
                  for e in rec["emails"]]
        blocks.append(Block(type="record", text="\n".join(parts),
                            anchor=Anchor(record_id=rec["case_number"]),
                            fields={k: rec[k] for k in ("case_number", "asset", "status",
                                                        "fault_code", "created")}))
    return ExtractResult(path=rel_path, fingerprint=fingerprint, extractor="salesforce",
                         extractor_version=VERSION, title=path.stem, blocks=blocks,
                         records=records,
                         pages=[PageCoverage(page=1, status="text",
                                             chars=sum(len(b.text) for b in blocks))])
