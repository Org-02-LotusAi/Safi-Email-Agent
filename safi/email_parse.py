"""Parse an inbound RFC822 message into an :class:`IncomingEmail` (doc §21, §22, §23).

The same parser is used for live IMAP bytes and for in-memory/test messages, so
behaviour is identical in both modes.
"""

from __future__ import annotations

import re
from email import message_from_bytes
from email.policy import default
from email.utils import parseaddr

from . import attachments as attach
from .models import IncomingEmail, ParsedAttachment
from .subject import canonicalize_subject, is_private_subject

# Markers that introduce forwarded / quoted history (doc §22).
_FORWARD_MARKERS = [
    r"-+\s*Forwarded message\s*-+",
    r"Begin forwarded message:",
    r"-+\s*Original Message\s*-+",
    r"^On .+ wrote:$",
    r"^From:\s.+$",  # classic Outlook forward header block
]
_FORWARD_RE = re.compile("|".join(f"(?:{m})" for m in _FORWARD_MARKERS),
                         re.IGNORECASE | re.MULTILINE)


def _strip_message_id(mid: str | None) -> str:
    if not mid:
        return ""
    return mid.strip().strip("<>").strip()


def _split_references(value: str | None) -> list[str]:
    if not value:
        return []
    return [_strip_message_id(tok) for tok in re.split(r"\s+", value.strip()) if tok.strip()]


def _get_body_text(msg) -> str:
    """Return the best plain-text body. Falls back to a crude HTML strip."""
    body = msg.get_body(preferencelist=("plain",))
    if body is not None:
        return body.get_content()
    html = msg.get_body(preferencelist=("html",))
    if html is not None:
        raw = html.get_content()
        return re.sub(r"<[^>]+>", " ", raw)
    # Non-multipart or unusual structure.
    try:
        content = msg.get_content()
        return content if isinstance(content, str) else ""
    except Exception:
        return ""


def _split_forwarded(body: str) -> tuple[str, str]:
    """Separate the freshly written portion from forwarded/quoted history.

    Returns (new_body, forwarded_text). Uses the earliest forward marker, and also
    treats a trailing block of ``>``-quoted lines as forwarded history.
    """
    forwarded_parts: list[str] = []
    new_body = body

    m = _FORWARD_RE.search(body)
    if m:
        new_body = body[: m.start()]
        forwarded_parts.append(body[m.start():].strip())

    # Collect quoted lines from whatever remains as the "new" portion.
    quoted, kept = [], []
    for line in new_body.splitlines():
        if line.lstrip().startswith(">"):
            quoted.append(line.lstrip().lstrip(">").strip())
        else:
            kept.append(line)
    if quoted:
        forwarded_parts.append("\n".join(q for q in quoted if q))
        new_body = "\n".join(kept)

    forwarded = "\n".join(p for p in forwarded_parts if p).strip()
    return new_body.strip(), forwarded


def _collect_attachments(msg) -> tuple[list[ParsedAttachment], list[str]]:
    """Return (parsed attachments, extra forwarded text from .eml parts)."""
    parsed: list[ParsedAttachment] = []
    eml_forwarded: list[str] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        disp = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        ctype = part.get_content_type()
        is_attachment = disp == "attachment" or (filename is not None and disp != "inline")
        is_eml = ctype == "message/rfc822"
        if not (is_attachment or is_eml):
            continue
        try:
            payload = part.get_payload(decode=True)
            if payload is None and is_eml:
                # message/rfc822 payload is a nested Message
                sub = part.get_payload()
                if isinstance(sub, list) and sub:
                    payload = sub[0].as_bytes()
        except Exception:
            payload = None
        if payload is None:
            continue
        fname = filename or ("forwarded.eml" if is_eml else "attachment.bin")
        pa = attach.extract(fname, payload)
        parsed.append(pa)
        if pa.ext == "eml" and pa.extracted_text:
            eml_forwarded.append(pa.extracted_text)
    return parsed, eml_forwarded


def parse_email(raw_bytes: bytes, delivered_to: str) -> IncomingEmail:
    """Parse raw message bytes delivered to ``delivered_to`` (an agent mailbox)."""
    msg = message_from_bytes(raw_bytes, policy=default)

    message_id = _strip_message_id(msg.get("Message-ID"))
    _, from_addr = parseaddr(msg.get("From", ""))
    sender = (from_addr or "").strip().lower()
    raw_subject = msg.get("Subject", "") or ""
    canonical = canonicalize_subject(raw_subject)

    in_reply_to = _strip_message_id(msg.get("In-Reply-To")) or None
    references = _split_references(msg.get("References"))
    thread_key = in_reply_to or (references[-1] if references else None)

    body_full = _get_body_text(msg)
    new_body, forwarded = _split_forwarded(body_full)

    parsed_attachments, eml_forwarded = _collect_attachments(msg)
    if eml_forwarded:
        forwarded = "\n\n".join([t for t in [forwarded, *eml_forwarded] if t]).strip()

    return IncomingEmail(
        message_id=message_id,
        sender=sender,
        delivered_to=(delivered_to or "").strip().lower(),
        raw_subject=raw_subject,
        canonical_subject=canonical,
        is_private=is_private_subject(canonical),
        body_text=new_body,
        forwarded_text=forwarded,
        in_reply_to=in_reply_to,
        references=references,
        thread_key=thread_key,
        attachments=parsed_attachments,
    )
