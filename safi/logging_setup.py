"""Structured JSON-lines logging (doc §38).

One JSON object per line on stdout. The log record has exactly the fields listed in the
doc: timestamp, agent_id, incoming_message_id, sender, canonical_subject, message_class,
micro_session_id, result, latency. There is deliberately NO parameter anywhere in this
module for passwords, API keys, full private attachments, or raw private training text —
callers cannot pass what does not exist as a parameter (doc §38).
"""

from __future__ import annotations

import json
import logging
import sys
import time

from .models import CLASS_PRIVATE, CLASS_WORK

_VALID_CLASSES = (CLASS_PRIVATE, CLASS_WORK)


def get_logger(name: str = "safi") -> logging.Logger:
    """Return a logger that emits one JSON object per line on stdout.

    Idempotent: calling this repeatedly for the same ``name`` does not stack handlers.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not any(isinstance(h, logging.StreamHandler) and getattr(h, "_safi_json", False)
               for h in logger.handlers):
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler._safi_json = True  # marker to keep this idempotent
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def log_event(
    logger: logging.Logger,
    *,
    agent_id: str,
    incoming_message_id: str | None,
    sender: str | None,
    canonical_subject: str | None,
    message_class: str,
    result: str,
    latency_ms: float,
    micro_session_id: str | None = None,
) -> None:
    """Emit one structured log record with exactly the doc §38 fields.

    ``message_class`` must be :data:`safi.models.CLASS_PRIVATE` or
    :data:`safi.models.CLASS_WORK`.
    """
    if message_class not in _VALID_CLASSES:
        raise ValueError(
            f"message_class must be one of {_VALID_CLASSES}, got {message_class!r}"
        )
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent_id": agent_id,
        "incoming_message_id": incoming_message_id,
        "sender": sender,
        "canonical_subject": canonical_subject,
        "message_class": message_class,
        "micro_session_id": micro_session_id,
        "result": result,
        "latency_ms": round(latency_ms, 2),
    }
    logger.info(json.dumps(record, ensure_ascii=True))
