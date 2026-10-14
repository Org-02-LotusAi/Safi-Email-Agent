"""LLM endpoint (doc §6 "one configured LLM endpoint").

Two implementations behind one tiny interface:

* :class:`AnthropicClient` — the live endpoint (Anthropic Claude). Imported lazily so the
  offline demo and the test-suite never require the ``anthropic`` package or an API key.
* :class:`FakeLlmClient` — a deterministic, offline "instruction-following" simulator. It
  applies training *directive* lines as its own policy and reflects the dynamic context it
  was given, which makes context routing observable in the acceptance tests. It never
  parrots non-directive private asides, mirroring the real model's isolation instruction.

The conversation itself is never the authoritative memory (doc §18) — the service owns
persistent state and rebuilds a fresh prompt every micro-session.
"""

from __future__ import annotations

import re
from typing import Protocol

from .context import (
    MARK_ATTACH,
    MARK_FORWARDED,
    MARK_MESSAGE,
    SECTION_REFERENCE,
    SECTION_SUBJECT,
    SECTION_TRAINING,
)


class LlmClient(Protocol):
    def complete(self, system: str, user: str, model: str, max_tokens: int) -> str:
        """Return the assistant's reply text for a single fresh exchange."""
        ...


# --- Live endpoint ---------------------------------------------------------
class AnthropicClient:
    """Calls the Anthropic Messages API. Credentials come from the environment
    (``ANTHROPIC_API_KEY``), never from code or config files (doc §5, §38)."""

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key
        self._client = None

    def _ensure(self):
        if self._client is None:
            import anthropic  # lazy: only required in live mode

            self._client = (
                anthropic.Anthropic(api_key=self._api_key)
                if self._api_key
                else anthropic.Anthropic()
            )
        return self._client

    def complete(self, system: str, user: str, model: str, max_tokens: int) -> str:
        client = self._ensure()
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        chunks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        return "\n".join(chunks).strip()


# --- Offline simulator -----------------------------------------------------
# Directive cue words: a training line containing one of these is treated as an
# operating rule the agent applies (and may reflect). Plain facts / asides are not
# reflected, so private asides are not leaked (doc §10, §12/TEST 10).
_DIRECTIVE_CUES = (
    "always", "never", "don't", "do not", "avoid", "keep", "ensure", "must",
    "should", "only", "prefer", "propose", "offer", "sign", "reply", "respond",
    "draft", "remember", "unless", "please", "use ", "when i", "help me", "manage",
)


def _is_directive(line: str) -> bool:
    low = line.lower()
    return any(cue in low for cue in _DIRECTIVE_CUES)


def _section(text: str, header: str) -> list[str]:
    """Return the lines belonging to a ``header`` section until the next blank-line
    boundary that precedes another header/marker."""
    out: list[str] = []
    lines = text.splitlines()
    capturing = False
    for ln in lines:
        if ln.strip() == header:
            capturing = True
            continue
        if capturing:
            if ln.startswith("# ") or ln.startswith("--- "):
                break
            out.append(ln)
    # trim leading/trailing blanks
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def _block_after(text: str, marker: str) -> str:
    """Text following a marker line until the next marker/section or double blank."""
    idx = text.find(marker)
    if idx < 0:
        return ""
    rest = text[idx + len(marker):]
    # drop the remainder of the marker line
    rest = rest.split("\n", 1)[1] if "\n" in rest else ""
    collected: list[str] = []
    for ln in rest.splitlines():
        if ln.startswith("# ") or ln.startswith("--- ") or ln.strip() == MARK_MESSAGE:
            break
        collected.append(ln)
    return "\n".join(collected).strip()


class FakeLlmClient:
    """Deterministic offline model. See module docstring."""

    def __init__(self, fail: bool = False, error_message: str = "simulated LLM failure"):
        self.fail = fail
        self.error_message = error_message
        self.calls: list[dict] = []  # recorded {system, user, model} for assertions

    def complete(self, system: str, user: str, model: str, max_tokens: int) -> str:
        self.calls.append({"system": system, "user": user, "model": model})
        if self.fail:
            raise RuntimeError(self.error_message)

        # Agent name from the first system line: "You are NAME, a trainable ..."
        m = re.match(r"You are (.+?),", system)
        name = m.group(1) if m else "the agent"

        directives = [
            ln[2:].strip()
            for ln in _section(system, SECTION_TRAINING)
            if ln.startswith("- ") and _is_directive(ln[2:])
        ]
        references = [ln.strip() for ln in _section(system, SECTION_REFERENCE) if ln.strip()]
        subject_summary = "\n".join(_section(user, SECTION_SUBJECT)).strip()
        forwarded = _block_after(user, MARK_FORWARDED)

        # Attachments: every "--- Attached document: NAME ---" block.
        attachments: list[tuple[str, str]] = []
        for am in re.finditer(re.escape(MARK_ATTACH) + r" (.+?) ---", user):
            fname = am.group(1)
            body = _block_after(user, am.group(0))
            attachments.append((fname, body))

        subj_m = re.search(r"^Subject: (.+)$", user, re.MULTILINE)
        subject = subj_m.group(1).strip() if subj_m else "your message"

        out = [f"Reply from {name}."]
        if directives:
            out.append("Following my guidance: " + " | ".join(directives))
        if references:
            out.append("Drawing on my reference material: " + " | ".join(references))
        if subject_summary:
            out.append("Continuing our prior context: " + subject_summary)
        if forwarded:
            out.append("Based on the forwarded history: " + forwarded[:800])
        for fname, body in attachments:
            if body:
                out.append(f"From the attached {fname}: " + body[:800])
        out.append(f'Regarding "{subject}": acknowledged; I will respond appropriately.')
        return "\n".join(out)
