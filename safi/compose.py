"""Build RFC822 messages (used by SMTP sending and by the in-memory transport/tests).

Keeping composition in one place means live email and offline messages are byte-identical
in structure, so the parser and the whole pipeline behave the same in both modes.
"""

from __future__ import annotations

import uuid
from email.message import EmailMessage
from email.utils import formatdate, make_msgid


def new_message_id(domain: str = "safi.local") -> str:
    try:
        return make_msgid(domain=domain).strip("<>")
    except Exception:
        return f"{uuid.uuid4().hex}@{domain}"


def make_message(
    sender: str,
    to: str,
    subject: str,
    body: str,
    *,
    message_id: str | None = None,
    in_reply_to: str | None = None,
    references: list[str] | None = None,
    attachments: list[tuple[str, bytes]] | None = None,
    display_name: str | None = None,
) -> bytes:
    """Compose a message and return its raw bytes.

    ``attachments`` is a list of (filename, data); the MIME subtype is derived from the
    file extension so TXT/PDF/DOCX arrive with sensible content types.
    """
    msg = EmailMessage()
    msg["From"] = f"{display_name} <{sender}>" if display_name else sender
    msg["To"] = to
    msg["Subject"] = subject
    mid = message_id or new_message_id()
    msg["Message-ID"] = f"<{mid}>"
    msg["Date"] = formatdate(localtime=True)
    if in_reply_to:
        msg["In-Reply-To"] = f"<{in_reply_to.strip('<>')}>"
    if references:
        msg["References"] = " ".join(f"<{r.strip('<>')}>" for r in references)
    msg.set_content(body or "")

    for filename, data in attachments or []:
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        maintype, subtype = {
            "txt": ("text", "plain"),
            "pdf": ("application", "pdf"),
            "docx": (
                "application",
                "vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            "eml": ("message", "rfc822"),
        }.get(ext, ("application", "octet-stream"))
        if maintype == "message":
            # message/rfc822 must carry a Message payload, not bytes.
            from email import message_from_bytes
            from email.policy import default as _default

            msg.add_attachment(
                message_from_bytes(data, policy=_default),
                maintype="message", subtype="rfc822", filename=filename,
            )
        else:
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    return msg.as_bytes()
