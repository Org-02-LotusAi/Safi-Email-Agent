"""Per-agent orchestration loop (doc §21, §36, §37, §38).

Wires together: transport fetch -> parse -> dedupe -> route Private/Work -> run ->
send reply/ack -> mark processed -> log. A single bad email must never stop the loop
(doc §37) — every failure path here is caught, logged, and returned as a record instead
of propagated.

Multi-tenancy (operator-requested extension beyond SOW §43, see safi/tenancy.py) is
layered in additively: when enabled, each inbound sender is routed to their own
isolated per-sender agent instance before the existing Private/Work logic runs. The
default (``multi_tenant=False``) preserves today's single-instance behaviour exactly.
"""

from __future__ import annotations

import time

from . import compose, tenancy
from .email_parse import parse_email
from .agent_runtime import run_micro_session
from .db import Store
from .llm import LlmClient
from .logging_setup import log_event
from .models import CLASS_PRIVATE, CLASS_WORK, AgentConfig, IncomingEmail
from .private_channel import handle_private
from .subject import reply_subject
from .transport import MailTransport


def _run_inbound(
    store: Store,
    agent: AgentConfig,
    llm: LlmClient,
    email: IncomingEmail,
    *,
    files_dir: str,
    logger,
    reject_policy: str = "reply",
    transport: MailTransport | None = None,
) -> dict:
    """Route a parsed, not-yet-processed ``email`` to Private or Work handling.

    Always returns a record containing whatever reply/ack/rejection text was
    produced (``reply_text`` for WORK, ``ack_text``/``rejection_text`` for
    PRIVATE) so non-email callers can read it. Only actually sends over the
    network when ``transport`` is not ``None``; when it is ``None`` the text is
    still returned, the message is still marked processed, and the event is
    still logged. Never raises (doc §37/TEST 20,21).
    """
    started = time.monotonic()
    message_class = CLASS_PRIVATE if email.is_private else CLASS_WORK
    micro_session_id = None
    result = "error"
    record: dict = {}

    try:
        if email.is_private:
            outcome = handle_private(store, agent, email, files_dir, reject_policy=reject_policy)
            if outcome.authorized:
                if outcome.ack_text and transport is not None:
                    transport.send(
                        agent,
                        email.sender,
                        "Re: Private",
                        outcome.ack_text,
                        in_reply_to=email.message_id,
                        references=[*email.references, email.message_id]
                        if email.message_id else email.references,
                    )
                store.mark_processed(agent.agent_id, email.message_id)
                result = "private_authorized"
                record = {
                    "status": "private_authorized",
                    "message_id": email.message_id,
                    "training_added": outcome.training_added,
                    "files_added": outcome.files_added,
                    "ack_text": outcome.ack_text,
                }
            else:
                if outcome.rejection_text and reject_policy == "reply" and transport is not None:
                    transport.send(
                        agent,
                        email.sender,
                        "Re: Private",
                        outcome.rejection_text,
                        in_reply_to=email.message_id,
                        references=[*email.references, email.message_id]
                        if email.message_id else email.references,
                    )
                # Unauthorized Private never modifies state; still mark processed so a
                # redelivered copy of the same rejected message is not re-sent forever.
                store.mark_processed(agent.agent_id, email.message_id)
                result = "private_rejected"
                record = {
                    "status": "private_rejected",
                    "message_id": email.message_id,
                    "rejection_text": outcome.rejection_text,
                }
            return record

        # Normal work (doc §19, §20, §21).
        res = run_micro_session(store, agent, email, llm)
        micro_session_id = res.micro_session_id
        if res.ok:
            if transport is not None:
                transport.send(
                    agent,
                    email.sender,
                    reply_subject(email.canonical_subject),
                    res.reply_text,
                    in_reply_to=email.message_id,
                    references=[*email.references, email.message_id]
                    if email.message_id else email.references,
                )
            store.mark_processed(agent.agent_id, email.message_id)
            result = "work_replied"
            record = {
                "status": "work_replied",
                "message_id": email.message_id,
                "micro_session_id": res.micro_session_id,
                "reply_text": res.reply_text,
            }
        else:
            # Controlled LLM failure (doc §37/TEST 20): do not mark processed, do not
            # crash — leave it eligible for a future retry/redelivery.
            result = "work_failed"
            record = {
                "status": "work_failed",
                "message_id": email.message_id,
                "micro_session_id": res.micro_session_id,
                "error": res.error,
                "reply_text": res.reply_text,
            }
        return record

    except Exception as exc:  # doc §37/TEST 20,21: one bad email never stops the loop
        result = "error"
        record = {"status": "error", "error": str(exc)}
        return record

    finally:
        latency_ms = (time.monotonic() - started) * 1000.0
        log_event(
            logger,
            agent_id=agent.agent_id,
            incoming_message_id=email.message_id,
            sender=email.sender,
            canonical_subject=email.canonical_subject,
            message_class=message_class,
            result=result,
            latency_ms=latency_ms,
            micro_session_id=micro_session_id,
        )


def process_message(
    store: Store,
    agent: AgentConfig,
    llm: LlmClient,
    transport: MailTransport,
    raw_bytes: bytes,
    *,
    files_dir: str,
    logger,
    reject_policy: str = "reply",
    multi_tenant: bool = False,
) -> dict:
    """Process one raw inbound message end to end. Never raises.

    When ``multi_tenant`` is True, the sender is routed to their own isolated
    per-sender agent instance (see :mod:`safi.tenancy`) before dedupe/handling.
    Default is False, which preserves pre-multi-tenancy behaviour exactly.
    """
    try:
        email = parse_email(raw_bytes, agent.mailbox)
    except Exception as exc:  # parsing itself failed; nothing to route
        log_event(
            logger,
            agent_id=agent.agent_id,
            incoming_message_id=None,
            sender=None,
            canonical_subject=None,
            message_class=CLASS_WORK,
            result="error",
            latency_ms=0.0,
        )
        return {"status": "error", "error": str(exc)}

    if multi_tenant:
        agent = tenancy.provision(store, agent, email.sender)

    # Duplicate-message protection (doc §36/TEST 19): do nothing else.
    if store.is_processed(agent.agent_id, email.message_id):
        return {"status": "duplicate", "message_id": email.message_id}

    return _run_inbound(
        store, agent, llm, email,
        files_dir=files_dir, logger=logger, reject_policy=reject_policy,
        transport=transport,
    )


def poll_agent_once(
    store: Store,
    agent: AgentConfig,
    llm: LlmClient,
    transport: MailTransport,
    *,
    files_dir: str,
    logger,
    reject_policy: str = "reply",
    multi_tenant: bool = False,
) -> list[dict]:
    """Fetch and process all currently-available new messages for ``agent``.

    A per-message exception is already caught inside :func:`process_message`; this loop
    additionally guards against a ``fetch_new`` failure (e.g. mailbox connection failure,
    doc §37) so one agent's transport trouble does not abort the batch.
    """
    records: list[dict] = []
    try:
        new_messages = transport.fetch_new(agent)
    except Exception as exc:
        log_event(
            logger,
            agent_id=agent.agent_id,
            incoming_message_id=None,
            sender=None,
            canonical_subject=None,
            message_class=CLASS_WORK,
            result=f"fetch_failed: {exc}",
            latency_ms=0.0,
        )
        return records

    for _uid, raw in new_messages:
        try:
            rec = process_message(
                store, agent, llm, transport, raw,
                files_dir=files_dir, logger=logger, reject_policy=reject_policy,
                multi_tenant=multi_tenant,
            )
        except Exception as exc:  # belt-and-suspenders; process_message already catches
            rec = {"status": "error", "error": str(exc)}
        records.append(rec)
    return records


def process_direct(
    store: Store,
    base_agent: AgentConfig,
    llm: LlmClient,
    *,
    from_email: str,
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes]] | None = None,
    files_dir: str,
    logger,
    multi_tenant: bool = True,
) -> dict:
    """Process one message built in-process (no transport required).

    Intended for non-email callers (e.g. an HTTP API) that want to hand SAFI a
    message directly. Composes an RFC822 message from the given fields, parses it
    exactly as the mail pipeline would, routes it to the sender's isolated tenant
    instance by default, and returns a record including the produced
    ``reply_text``/``ack_text``/``rejection_text`` — no transport is required or used.
    """
    raw = compose.make_message(
        sender=from_email, to=base_agent.mailbox, subject=subject, body=body,
        attachments=attachments,
    )
    email = parse_email(raw, base_agent.mailbox)

    agent = tenancy.provision(store, base_agent, email.sender) if multi_tenant else base_agent

    if store.is_processed(agent.agent_id, email.message_id):
        return {"status": "duplicate", "message_id": email.message_id}

    return _run_inbound(
        store, agent, llm, email,
        files_dir=files_dir, logger=logger, transport=None,
    )


def run(settings) -> None:
    """Live polling loop across all enabled agents (doc §37).

    Imports config lazily to avoid a circular import (config.py builds Settings from this
    module's types only at the type-hint level).
    """
    from .config import build_llm  # lazy import to avoid a config<->service cycle
    from .transport import ImapSmtpTransport
    from .logging_setup import get_logger

    logger = get_logger()
    store = Store(settings.db_path)
    llm = build_llm(settings)

    transports: dict[str, ImapSmtpTransport] = {
        agent.agent_id: ImapSmtpTransport() for agent in settings.agents if agent.enabled
    }

    try:
        while True:
            for agent in settings.agents:
                if not agent.enabled:
                    continue
                transport = transports[agent.agent_id]
                try:
                    poll_agent_once(
                        store, agent, llm, transport,
                        files_dir=settings.files_dir, logger=logger,
                        reject_policy=settings.reject_policy,
                        multi_tenant=settings.multi_tenant,
                    )
                except Exception as exc:
                    # A connection failure for one agent must not kill the others (§37).
                    log_event(
                        logger,
                        agent_id=agent.agent_id,
                        incoming_message_id=None,
                        sender=None,
                        canonical_subject=None,
                        message_class=CLASS_WORK,
                        result=f"poll_failed: {exc}",
                        latency_ms=0.0,
                    )
            for agent in settings.agents:
                if not agent.enabled:
                    continue
                transports[agent.agent_id].idle_wait(agent, timeout=settings.poll_interval)
    except KeyboardInterrupt:
        pass
    finally:
        store.close()
