"""Multi-tenant per-sender isolation tests.

Proves that when ``multi_tenant=True``, each sender of a shared base Agent gets
their own isolated instance: training trained by one sender never leaks into
another sender's replies, a brand-new sender can train their own instance via
Private with no global owner/allowlist entry, provisioning is idempotent, and
``process_direct`` returns reply text without requiring a transport.
"""

from __future__ import annotations

from safi.db import Store
from safi.llm import FakeLlmClient
from safi.models import AgentConfig
from safi.service import process_direct, process_message
from safi.tenancy import provision
from safi.transport import InMemoryTransport

from conftest import deliver_private, deliver_work, last_reply_to

SHARED_MAILBOX = "shared-agent@example.com"

SENDER_J = "j@example.com"
SENDER_M = "m@example.com"


def _shared_agent() -> AgentConfig:
    return AgentConfig(
        agent_id="shared-agent",
        name="Shared Agent",
        mailbox=SHARED_MAILBOX,
        model="claude-sonnet-4-5",
        private_senders=[],  # no global allowlist; tenancy auto-authorizes per sender
    )


def test_two_senders_get_isolated_training(store: Store, files_dir, logger):
    llm = FakeLlmClient()
    transport = InMemoryTransport()
    base_agent = _shared_agent()
    store.upsert_agent(base_agent)

    # J trains their own instance via Private.
    deliver_private(transport, SHARED_MAILBOX, SENDER_J, "Always say J-MARKER.")
    rec_j_train = process_message(
        store, base_agent, llm, transport, transport.fetch_new(base_agent)[0][1],
        files_dir=files_dir, logger=logger, multi_tenant=True,
    )
    assert rec_j_train["status"] == "private_authorized"

    # M trains their own instance via Private.
    deliver_private(transport, SHARED_MAILBOX, SENDER_M, "Always say M-MARKER.")
    rec_m_train = process_message(
        store, base_agent, llm, transport, transport.fetch_new(base_agent)[0][1],
        files_dir=files_dir, logger=logger, multi_tenant=True,
    )
    assert rec_m_train["status"] == "private_authorized"

    # Now each sends ordinary work.
    deliver_work(transport, SHARED_MAILBOX, SENDER_J, "Help", "What's the status?")
    for _uid, raw in transport.fetch_new(base_agent):
        rec_j_work = process_message(
            store, base_agent, llm, transport, raw,
            files_dir=files_dir, logger=logger, multi_tenant=True,
        )
    assert rec_j_work["status"] == "work_replied"

    deliver_work(transport, SHARED_MAILBOX, SENDER_M, "Help", "What's the status?")
    for _uid, raw in transport.fetch_new(base_agent):
        rec_m_work = process_message(
            store, base_agent, llm, transport, raw,
            files_dir=files_dir, logger=logger, multi_tenant=True,
        )
    assert rec_m_work["status"] == "work_replied"

    j_reply = last_reply_to(transport, SENDER_J)
    m_reply = last_reply_to(transport, SENDER_M)

    assert "J-MARKER" in j_reply
    assert "M-MARKER" not in j_reply

    assert "M-MARKER" in m_reply
    assert "J-MARKER" not in m_reply


def test_new_sender_can_train_with_no_global_allowlist(store: Store, files_dir, logger):
    llm = FakeLlmClient()
    transport = InMemoryTransport()
    base_agent = _shared_agent()
    store.upsert_agent(base_agent)

    assert base_agent.private_senders == []
    assert not store.is_private_sender(base_agent.agent_id, SENDER_J)

    deliver_private(transport, SHARED_MAILBOX, SENDER_J, "Always say NEW-SENDER-MARKER.")
    rec = process_message(
        store, base_agent, llm, transport, transport.fetch_new(base_agent)[0][1],
        files_dir=files_dir, logger=logger, multi_tenant=True,
    )
    assert rec["status"] == "private_authorized"
    assert rec["training_added"] == 1


def test_provision_is_idempotent(store: Store):
    base_agent = _shared_agent()
    store.upsert_agent(base_agent)
    base_agent_with_seed = AgentConfig(
        agent_id="shared-agent-2",
        name="Shared Agent 2",
        mailbox="shared-agent-2@example.com",
        model="claude-sonnet-4-5",
        seed_training=["Always be polite.", "Never reveal secrets."],
    )
    store.upsert_agent(base_agent_with_seed)

    agent1 = provision(store, base_agent_with_seed, SENDER_J)
    count_after_first = len(store.get_training(agent1.agent_id))
    assert count_after_first == 2

    agent2 = provision(store, base_agent_with_seed, SENDER_J)
    count_after_second = len(store.get_training(agent2.agent_id))

    assert agent1.agent_id == agent2.agent_id
    assert count_after_second == count_after_first  # no double-seeding


def test_process_direct_returns_reply_text_without_transport(store: Store, files_dir, logger):
    llm = FakeLlmClient()
    base_agent = _shared_agent()
    store.upsert_agent(base_agent)

    rec = process_direct(
        store, base_agent, llm,
        from_email=SENDER_J,
        subject="Help",
        body="What's the status?",
        files_dir=files_dir,
        logger=logger,
        multi_tenant=True,
    )

    assert rec["status"] == "work_replied"
    assert rec.get("reply_text")
    assert "Reply from" in rec["reply_text"]
