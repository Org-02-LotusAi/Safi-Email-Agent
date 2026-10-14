"""Load ``agents.yaml`` into runtime :class:`Settings` (doc §34, §42).

Secrets (IMAP/SMTP passwords) are never read from the yaml file itself — only a
``password_env`` key naming an environment variable is accepted, and the value is
resolved from ``os.environ`` at load time (doc §38: never log/store raw secrets).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

from .db import Store
from .llm import AnthropicClient, FakeLlmClient, LlmClient
from .models import AgentConfig


@dataclass
class Settings:
    db_path: str
    files_dir: str
    llm_mode: str  # "anthropic" | "fake"
    default_model: str
    reject_policy: str
    poll_interval: int
    agents: list[AgentConfig] = field(default_factory=list)
    multi_tenant: bool = True


def _resolve_secret(block: dict | None) -> dict | None:
    """Return a copy of an imap/smtp config block with ``password_env`` resolved to
    ``password`` via the environment. Never accepts a literal ``password`` in yaml.

    Resolution is intentionally NON-fatal: a missing environment variable leaves
    ``password`` as ``None`` and preserves ``password_env`` so callers that actually need
    to connect (``run``) can report exactly which variable is unset — while commands that
    never touch the network (``init-db``) load the config without needing any secret.
    """
    if not block:
        return None
    resolved = dict(block)
    env_name = resolved.get("password_env")
    if env_name:
        resolved["password"] = os.environ.get(env_name)  # may be None; validated lazily
    return resolved


def missing_secrets(settings: "Settings") -> list[str]:
    """Return the names of ``password_env`` variables required by enabled agents that are
    not set. Used as a pre-flight check before starting the live loop (``run``)."""
    missing: list[str] = []
    for agent in settings.agents:
        if not agent.enabled:
            continue
        for block in (agent.imap, agent.smtp):
            if not block:
                continue
            env_name = block.get("password_env")
            if env_name and not block.get("password"):
                missing.append(env_name)
    return sorted(set(missing))


def _choose_llm_mode() -> str:
    env_mode = os.environ.get("SAFI_LLM")
    if env_mode:
        return env_mode
    return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "fake"


def load_config(path: str) -> Settings:
    """Parse a YAML config file into a :class:`Settings` instance.

    Top-level keys: ``db_path``, ``files_dir``, ``default_model``, ``reject_policy``,
    ``poll_interval``, ``agents`` (list). Each agent entry maps to an
    :class:`AgentConfig`; its ``imap``/``smtp`` blocks may use ``password_env`` instead
    of a literal password.
    """
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    default_model = raw.get("default_model", "claude-sonnet-4-5")
    agents: list[AgentConfig] = []
    for entry in raw.get("agents", []) or []:
        agents.append(
            AgentConfig(
                agent_id=entry["agent_id"],
                name=entry.get("name", entry["agent_id"]),
                mailbox=entry["mailbox"],
                model=entry.get("model", default_model),
                enabled=entry.get("enabled", True),
                private_senders=list(entry.get("private_senders", []) or []),
                imap=_resolve_secret(entry.get("imap")),
                smtp=_resolve_secret(entry.get("smtp")),
                max_output_tokens=entry.get("max_output_tokens", 1024),
                seed_training=list(entry.get("seed_training", []) or []),
            )
        )

    return Settings(
        db_path=raw.get("db_path", "./data/safi.sqlite"),
        files_dir=raw.get("files_dir", "./data/files"),
        llm_mode=_choose_llm_mode(),
        default_model=default_model,
        reject_policy=raw.get("reject_policy", "reply"),
        poll_interval=int(raw.get("poll_interval", 60)),
        agents=agents,
        multi_tenant=bool(raw.get("multi_tenant", True)),
    )


def build_llm(settings: Settings) -> LlmClient:
    """Return the configured :class:`LlmClient` implementation."""
    if settings.llm_mode == "fake":
        return FakeLlmClient()
    return AnthropicClient()


def apply_seed(store: Store, agents: list[AgentConfig]) -> None:
    """Idempotent bootstrap: upsert each agent, register its private senders, and seed
    its INSTRUCTION training ONLY if it has no training yet (doc §7, §26).
    """
    for agent in agents:
        store.upsert_agent(agent)
        for sender in agent.normalized_private_senders():
            store.add_private_sender(agent.agent_id, sender)
        if agent.seed_training and not store.get_training(agent.agent_id):
            for line in agent.seed_training:
                line = (line or "").strip()
                if line:
                    store.add_training(agent.agent_id, "INSTRUCTION", line)
