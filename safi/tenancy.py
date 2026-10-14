"""Multi-tenant per-sender agent instances.

This module implements an ADDITIVE multi-tenancy layer on top of the existing
single-instance Agent model. The operator's request is: every email SENDER that
contacts a given base Agent gets their OWN fully isolated instance of that agent —
own training, own reference files, own (client, subject) context, own micro-session
history, own processed-message dedupe — invisible to every other sender. This is
intentionally BEYOND the scope described in SOW doc §43 ("no agent-to-agent
workflows" / one Agent Instance per mailbox), per explicit operator request to add
tenant isolation without changing the mailbox-per-agent model.

No schema change is required. ``training``, ``files``, ``subject_context``,
``micro_sessions``, and ``processed_messages`` are all already keyed by an arbitrary
``agent_id`` string (see safi/db.py). A per-sender instance is simply the existing
runtime keyed by a synthetic, deterministic agent id:

    "{base_agent_id}::{sender_email_lowercased}"

Routing to this synthetic id is what makes every downstream module (context
assembly, training lookup, subject-context, micro-session history, dedupe) isolated
per sender with ZERO changes to those modules.

Important: tenant instances are deliberately NEVER upserted into the ``agents``
table. That table's ``mailbox`` column is UNIQUE and every tenant instance of a
given base agent shares the same mailbox (the base agent's own mailbox) — there is
only one real mailbox being polled. Only ``private_senders``/``training``/etc. rows
are written for a tenant instance id.
"""

from __future__ import annotations

from dataclasses import replace

from .db import Store
from .models import AgentConfig

INSTANCE_SEP = "::"


def instance_id(base_agent_id: str, sender_email: str) -> str:
    """Return the synthetic per-sender instance id for ``base_agent_id``."""
    return f"{base_agent_id}{INSTANCE_SEP}{(sender_email or '').strip().lower()}"


def is_instance_id(agent_id: str) -> bool:
    """True if ``agent_id`` is a synthetic per-sender instance id."""
    return INSTANCE_SEP in (agent_id or "")


def split_instance(agent_id: str) -> tuple[str, str | None]:
    """Split an agent id into (base_agent_id, tenant_email_or_None).

    Returns ``(agent_id, None)`` unchanged when ``agent_id`` is not an instance id.
    """
    if INSTANCE_SEP in (agent_id or ""):
        base, _, tenant = agent_id.partition(INSTANCE_SEP)
        return base, tenant
    return agent_id, None


def tenant_agent(base: AgentConfig, sender_email: str) -> AgentConfig:
    """Return a per-sender AgentConfig derived from ``base``.

    Same mailbox/model/etc. as ``base``; only ``agent_id`` and ``private_senders``
    differ so the sender is auto-authorized to train their own isolated instance.
    """
    tenant = (sender_email or "").strip().lower()
    return replace(
        base,
        agent_id=instance_id(base.agent_id, tenant),
        private_senders=[tenant],
    )


def provision(store: Store, base: AgentConfig, sender_email: str) -> AgentConfig:
    """Return the per-sender tenant AgentConfig, provisioning it on first contact.

    First contact for a given (base agent, sender) pair registers the sender as
    that tenant instance's sole authorized Private sender (so they may train their
    own instance with no global owner/allowlist entry needed) and, if the base
    agent defines ``seed_training``, seeds it into the new instance exactly once.
    Safe to call on every inbound message — idempotent after the first call.
    """
    agent = tenant_agent(base, sender_email)
    tenant = (sender_email or "").strip().lower()

    if not store.is_private_sender(agent.agent_id, tenant):
        store.add_private_sender(agent.agent_id, tenant)
        if base.seed_training and not store.get_training(agent.agent_id):
            for line in base.seed_training:
                line = (line or "").strip()
                if line:
                    store.add_training(agent.agent_id, "INSTRUCTION", line)

    return agent
