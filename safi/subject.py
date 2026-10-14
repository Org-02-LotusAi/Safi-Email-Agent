"""Subject canonicalization and the reserved ``Private`` subject (doc §14, §9, §16).

Every normal email maps to a Canonical Subject. Ordinary prefixes (Re:/RE:/Fwd:/FW:)
are stripped, whitespace and case are normalized *for matching*, and the case is kept
for display/replies. ``Private`` is a reserved canonical subject that belongs to the
control plane and must never be treated as an ordinary task subject.
"""

from __future__ import annotations

import re

PRIVATE_SUBJECT = "Private"

# Leading reply/forward prefix chain, e.g. "RE: Fwd: ", case-insensitive, repeated.
_PREFIX_RE = re.compile(r"^\s*(?:(?:re|fwd|fw)\s*:\s*)+", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def canonicalize_subject(raw: str | None) -> str:
    """Return the Canonical Subject: prefix chain removed, whitespace collapsed, trimmed.

    Case is preserved (the first form seen wins for display); matching is done via
    :func:`subject_key`. Examples (doc §14) all canonicalize to ``Contract Renewal``::

        "Contract Renewal", "Re: Contract Renewal", "Fwd: Contract Renewal",
        "RE: Fwd: Contract Renewal"  ->  "Contract Renewal"
    """
    if not raw:
        return ""
    s = _PREFIX_RE.sub("", raw)
    s = _WS_RE.sub(" ", s).strip()
    return s


def subject_key(canonical: str) -> str:
    """The namespace key used for persistence lookups — casefolded canonical subject."""
    return canonicalize_subject(canonical).casefold()


def is_private_subject(canonical: str) -> bool:
    """True when the canonical subject is the reserved ``Private`` control subject (§9)."""
    return subject_key(canonical) == PRIVATE_SUBJECT.casefold()


def reply_subject(canonical: str) -> str:
    """Build a normal reply subject with exactly one ``Re: `` prefix (doc §33)."""
    core = canonicalize_subject(canonical)
    if not core:
        return "Re:"
    return f"Re: {core}"
