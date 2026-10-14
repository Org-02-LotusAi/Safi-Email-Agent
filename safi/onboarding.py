"""The onboarding instructions email (sent by ``POST /v1/onboard``).

When a user clicks the "Get my Safi assistant" button in the meeting-manager platform, the
platform calls the onboard endpoint, which emails that user the instructions below so they
know exactly how to use the service. Kept here so the copy is easy to review/edit and is
unit-testable independently of the HTTP layer.
"""

from __future__ import annotations

from .models import AgentConfig

ONBOARDING_SUBJECT = "Your Safi AI assistants — how to use them"


def build_onboarding_email(agents: list[AgentConfig], name: str | None = None) -> tuple[str, str]:
    """Return (subject, body) for the onboarding instructions email.

    Lists the available agent mailboxes and explains how to send work, how to personalise
    (train) a private assistant, and that each person's assistant is isolated to them.
    """
    greeting = f"Hi {name}," if name else "Hi,"
    agent_lines = [
        f"  - {a.name}: {a.mailbox}"
        for a in agents if a.enabled
    ]
    agents_block = "\n".join(agent_lines) if agent_lines else "  (no assistants configured)"

    body = f"""{greeting}

You now have your own AI assistants that you can use entirely by email. They are private to
you — what you tell them and what they learn is yours alone and is not shared with anyone else.

YOUR ASSISTANTS
{agents_block}

HOW TO USE THEM
1. Send work by email. Just email an assistant above with your request as an ordinary email
   (any subject). It will reply with a helpful, contextual answer. You can forward an existing
   email thread and ask it to draft a reply, and you can attach documents (TXT, PDF, or DOCX)
   for it to use.

2. Personalise your assistant (optional). To teach it how you like things done, email it with
   the subject line exactly:  Private
   Then write your instructions in plain English, for example:
     "Always keep replies short and professional."
     "When scheduling, only propose times Monday-Friday, 9am-5pm, and confirm my timezone."
   You'll get a short confirmation. From then on your assistant follows your guidance — and
   only your copy is affected.

3. It remembers. Your assistant keeps track of your ongoing conversations by topic, so later
   emails on the same subject build on what came before.

A few notes:
  - Your assistant only reads its mailbox and sends email replies. It never takes other
    actions on your behalf.
  - Each assistant is personal to you; other people get their own separate assistants.

That's it — send one of the addresses above an email and you're started.

— The Safi Team
"""
    return ONBOARDING_SUBJECT, body
