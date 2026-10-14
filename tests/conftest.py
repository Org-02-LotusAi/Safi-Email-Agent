"""Shared pytest fixtures for the SAFI Product 009 test suite.

Everything here is built strictly from the frozen interfaces in safi/*.py (see plan.md
and _doc_extracted.txt). No safi/*.py file is modified by this test suite.
"""

from __future__ import annotations

import io
import os

import pytest

from safi import compose
from safi.db import Store
from safi.llm import FakeLlmClient
from safi.logging_setup import get_logger
from safi.models import AgentConfig
from safi.transport import InMemoryTransport

OWNER = "owner@example.com"

AGENT_A_MAILBOX = "reply-agent@example.com"
AGENT_B_MAILBOX = "schedule-agent@example.com"


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "safi.sqlite")


@pytest.fixture
def store(db_path):
    s = Store(db_path)
    yield s
    s.close()


@pytest.fixture
def files_dir(tmp_path):
    d = tmp_path / "files"
    d.mkdir(exist_ok=True)
    return str(d)


@pytest.fixture
def logger():
    return get_logger("safi-test")


@pytest.fixture
def transport():
    return InMemoryTransport()


@pytest.fixture
def llm():
    return FakeLlmClient()


@pytest.fixture
def agent_a():
    """Agent A: Email Keeper (reply-agent@example.com), authorized owner registered
    by the ``store`` fixture usage below."""
    return AgentConfig(
        agent_id="agent-a",
        name="Email Keeper",
        mailbox=AGENT_A_MAILBOX,
        model="claude-sonnet-4-5",
        private_senders=[OWNER],
    )


@pytest.fixture
def agent_b():
    """Agent B: Schedule Keeper (schedule-agent@example.com)."""
    return AgentConfig(
        agent_id="agent-b",
        name="Schedule Keeper",
        mailbox=AGENT_B_MAILBOX,
        model="claude-sonnet-4-5",
        private_senders=[OWNER],
    )


@pytest.fixture
def setup_agents(store, agent_a, agent_b):
    """Upsert both agents and register their authorized private sender (owner@example.com)."""
    store.upsert_agent(agent_a)
    store.upsert_agent(agent_b)
    for sender in agent_a.normalized_private_senders():
        store.add_private_sender(agent_a.agent_id, sender)
    for sender in agent_b.normalized_private_senders():
        store.add_private_sender(agent_b.agent_id, sender)
    return agent_a, agent_b


# --- helpers ------------------------------------------------------------------


def deliver_work(transport, to_mailbox, sender, subject, body, **kw):
    """Compose an ordinary work email and deliver it into ``to_mailbox``'s inbox.

    ``**kw`` forwards to compose.make_message (message_id, in_reply_to, references,
    attachments).
    """
    raw = compose.make_message(
        sender=sender, to=to_mailbox, subject=subject, body=body, **kw
    )
    transport.deliver(to_mailbox, raw)
    return raw


def deliver_private(transport, to_mailbox, sender, body, **kw):
    """Compose a Subject: Private control-plane email and deliver it."""
    return deliver_work(transport, to_mailbox, sender, "Private", body, **kw)


def last_reply_to(transport, addr) -> str:
    """Return the body of the most recently sent message to ``addr``."""
    sent = transport.sent_to(addr)
    assert sent, f"no message was ever sent to {addr}"
    return sent[-1]["body"]


def make_pdf_bytes(text: str) -> bytes:
    """Build a minimal single-page PDF containing ``text`` using fpdf2."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in text.splitlines() or [text]:
        pdf.multi_cell(0, 10, line)
    out = pdf.output()
    if isinstance(out, str):
        return out.encode("latin-1")
    return bytes(out)


def make_docx_bytes(text: str) -> bytes:
    """Build a minimal .docx containing ``text`` using python-docx."""
    import docx

    document = docx.Document()
    for line in text.splitlines() or [text]:
        document.add_paragraph(line)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()
