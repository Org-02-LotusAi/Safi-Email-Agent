"""Core data structures shared across the service.

These are plain dataclasses so they are trivial to construct in tests and to serialise
into log records. They carry no behaviour beyond light validation helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# --- Training categories (doc §26). Natural-language messages are sufficient; these are
# used only to tag stored training, never required syntax from the sender. ---
TRAINING_CATEGORIES = (
    "INSTRUCTION",
    "FACT",
    "PREFERENCE",
    "EXAMPLE",
    "REFERENCE_FILE",
    "CORRECTION",
    "OPERATING_RULE",
)

# Message classes for logging (doc §38).
CLASS_PRIVATE = "PRIVATE"
CLASS_WORK = "WORK"


@dataclass
class AgentConfig:
    """A Trainable Agent Instance (doc §7). Two instances run the same code but differ
    entirely through the fields below plus their persisted training/context."""

    agent_id: str
    name: str
    mailbox: str                       # the agent's ordinary email address
    model: str                         # LLM model id for this agent's endpoint
    enabled: bool = True
    private_senders: list[str] = field(default_factory=list)  # authorized Private senders
    # Transport credentials for live mode. Absent in offline/demo/test mode.
    imap: dict | None = None           # {host, port, user, password, ssl}
    smtp: dict | None = None           # {host, port, user, password, starttls}
    max_output_tokens: int = 1024
    # Optional seed training applied on first init (equivalent to sending Private mail).
    seed_training: list[str] = field(default_factory=list)

    def normalized_private_senders(self) -> set[str]:
        return {s.strip().lower() for s in self.private_senders if s and s.strip()}


@dataclass
class ParsedAttachment:
    """An attachment pulled from an email (doc §24)."""

    filename: str
    content_type: str
    data: bytes
    supported: bool                    # True for .txt/.pdf/.docx/.eml
    extracted_text: str | None = None  # None when unsupported or extraction failed
    error: str | None = None           # populated when extraction failed (never raised)

    @property
    def ext(self) -> str:
        _, _, e = self.filename.lower().rpartition(".")
        return e if _ else ""


@dataclass
class IncomingEmail:
    """A parsed inbound message (doc §21)."""

    message_id: str
    sender: str                        # normalized lower-case address of the From header
    delivered_to: str                  # the agent mailbox this arrived at
    raw_subject: str
    canonical_subject: str             # doc §14
    is_private: bool                   # canonical subject == reserved "Private" (doc §9)
    body_text: str
    forwarded_text: str = ""           # forwarded/quoted material (dynamic context, §22)
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    thread_key: str | None = None      # standards-based thread association (§23)
    attachments: list[ParsedAttachment] = field(default_factory=list)

    @property
    def client_id(self) -> str:
        """For Product 009 the sender address is the Client identity (doc §13)."""
        return self.sender


@dataclass
class MicroSessionResult:
    """Outcome of one fresh micro-session (doc §19, §20)."""

    micro_session_id: str
    agent_id: str
    client_id: str
    canonical_subject: str
    incoming_message_id: str
    reply_text: str
    result_summary: str
    started_at: str
    ended_at: str
    ok: bool = True
    error: str | None = None
