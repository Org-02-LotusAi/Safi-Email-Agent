"""Generic, use-case-neutral Agent runtime (doc §39 Step 1, §19).

This module knows nothing about Email Keeper / Schedule Keeper / any specific agent. It
loads training + context, assembles a prompt, starts a *fresh* micro-session for every
normal task, calls the model, and persists a compact (Client, Subject) summary. The same
code specializes purely through each agent's training/configuration (doc §2, §31).
"""

from __future__ import annotations

from .context import assemble
from .db import Store
from .llm import LlmClient
from .models import AgentConfig, IncomingEmail, MicroSessionResult
from .subject import subject_key

_SUMMARY_CAP = 1600  # keep persisted (Client, Subject) context compact (doc §28)


def _update_subject_summary(store: Store, agent: AgentConfig, email: IncomingEmail,
                            reply_text: str) -> None:
    """Append a compact note to the persistent (Client, Subject) summary (doc §28)."""
    key = subject_key(email.canonical_subject)
    prior_row = store.get_subject_context(agent.agent_id, email.client_id, key)
    prior = (prior_row["summary"] if prior_row else "") or ""

    request_gist = " ".join((email.body_text or "").split())[:200]
    note = f"- Client asked: {request_gist}" if request_gist else "- (interaction with no body)"
    combined = (prior + "\n" + note).strip() if prior else note
    if len(combined) > _SUMMARY_CAP:  # keep the most recent context
        combined = combined[-_SUMMARY_CAP:]

    store.upsert_subject_context(
        agent_id=agent.agent_id,
        client_id=email.client_id,
        canonical_key=key,
        display_subject=email.canonical_subject,
        summary=combined,
    )


def run_micro_session(store: Store, agent: AgentConfig, email: IncomingEmail,
                      llm: LlmClient) -> MicroSessionResult:
    """Run one fresh micro-session for a normal (non-Private) task (doc §19, §20).

    On LLM failure the session is recorded as a controlled failure and the exception is
    NOT propagated, so subsequent messages continue (doc §37, TEST 20).
    """
    msid, started = store.start_micro_session(
        agent.agent_id, email.client_id, email.canonical_subject, email.message_id
    )
    system, user = assemble(store, agent, email)

    try:
        reply = llm.complete(system, user, agent.model, agent.max_output_tokens)
    except Exception as exc:
        summary = f"LLM failure: {type(exc).__name__}: {exc}"
        ended = store.end_micro_session(msid, summary)
        return MicroSessionResult(
            micro_session_id=msid, agent_id=agent.agent_id, client_id=email.client_id,
            canonical_subject=email.canonical_subject, incoming_message_id=email.message_id,
            reply_text="", result_summary=summary, started_at=started, ended_at=ended,
            ok=False, error=str(exc),
        )

    # Persist compact context only after a successful reply (doc §28).
    _update_subject_summary(store, agent, email, reply)
    result_summary = f"Replied to {email.client_id} re '{email.canonical_subject}'."
    ended = store.end_micro_session(msid, result_summary)

    return MicroSessionResult(
        micro_session_id=msid, agent_id=agent.agent_id, client_id=email.client_id,
        canonical_subject=email.canonical_subject, incoming_message_id=email.message_id,
        reply_text=reply, result_summary=result_summary, started_at=started, ended_at=ended,
        ok=True,
    )
