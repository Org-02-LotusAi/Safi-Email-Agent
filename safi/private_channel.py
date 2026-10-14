"""The reserved ``Subject: Private`` control plane (doc §9-§12, §25-§27).

A Private message may modify Agent state ONLY when its sender is on that Agent's
authorized Private-sender allowlist (doc §10). Unauthorized Private messages never modify
training/memory and are logged and (optionally) rejected (doc §11). Private content may
influence behaviour but is isolated — never echoed back merely for having been used
(doc §12); the acknowledgement is concise and does not echo the training (doc §27).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field

from .db import Store
from .models import AgentConfig, IncomingEmail


@dataclass
class PrivateOutcome:
    authorized: bool
    training_added: int = 0
    files_added: int = 0
    ack_text: str | None = None          # concise ack to send to the authorized sender
    rejection_text: str | None = None    # controlled rejection (policy-dependent)
    notes: list[str] = field(default_factory=list)


def _persist_private_files(store: Store, agent: AgentConfig, email: IncomingEmail,
                           files_dir: str) -> int:
    """Authorized Private attachments may become persistent reference material (doc §25)."""
    added = 0
    os.makedirs(files_dir, exist_ok=True)
    for att in email.attachments:
        if not att.supported:
            continue  # unsupported types are ignored, never crash (doc §24)
        location = os.path.join(files_dir, f"{agent.agent_id}_{uuid.uuid4().hex}_{att.filename}")
        try:
            with open(location, "wb") as fh:
                fh.write(att.data)
        except OSError:
            location = f"(memory)://{att.filename}"  # persistence of bytes best-effort
        store.add_file(
            agent_id=agent.agent_id,
            filename=att.filename,
            location=location,
            extracted_text=att.extracted_text,
            source_message_id=email.message_id,
        )
        added += 1
    return added


def handle_private(store: Store, agent: AgentConfig, email: IncomingEmail,
                   files_dir: str, reject_policy: str = "reply") -> PrivateOutcome:
    """Process a Private-subject message. Returns a :class:`PrivateOutcome`.

    ``reject_policy`` is either ``"reply"`` (send a controlled rejection) or ``"ignore"``.
    State is modified only for authorized senders.
    """
    authorized = store.is_private_sender(agent.agent_id, email.sender)
    if not authorized:
        # Do NOT modify training/memory or ingest attachments as knowledge (doc §11).
        outcome = PrivateOutcome(authorized=False)
        outcome.notes.append("unauthorized private sender rejected")
        if reject_policy == "reply":
            outcome.rejection_text = (
                "This address is not authorized to train this assistant. "
                "No changes were made."
            )
        return outcome

    # Authorized: persist natural-language training (no special syntax required, doc §26).
    training_added = 0
    body = (email.body_text or "").strip()
    if body:
        store.add_training(
            agent_id=agent.agent_id,
            category="INSTRUCTION",
            content=body,
            source_message_id=email.message_id,
        )
        training_added = 1

    files_added = _persist_private_files(store, agent, email, files_dir)

    # Concise acknowledgement — does not echo the private training content (doc §27).
    bits = []
    if training_added:
        bits.append("your instructions")
    if files_added:
        bits.append(f"{files_added} reference file(s)")
    what = " and ".join(bits) if bits else "your message"
    ack = f"Training received: {what} have been stored and will guide my future replies."

    return PrivateOutcome(
        authorized=True,
        training_added=training_added,
        files_added=files_added,
        ack_text=ack,
    )
