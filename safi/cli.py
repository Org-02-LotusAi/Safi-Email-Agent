"""``python -m safi`` command-line entry points.

Commands:
  init-db   Load a config file, create/upgrade the SQLite schema, apply seed data.
  run       Load a config file and run the live IMAP/SMTP polling loop.
  demo      Fully offline, credential-free proof that two Trainable Agent Instances
            differentiate purely through training (doc §18/§31/TEST 18).
"""

from __future__ import annotations

import argparse
import sys

from . import compose, service
from .config import apply_seed, build_llm, load_config, missing_secrets
from .db import Store, init_db
from .llm import FakeLlmClient
from .logging_setup import get_logger
from .models import AgentConfig
from .transport import InMemoryTransport


def _cmd_init_db(args: argparse.Namespace) -> int:
    settings = load_config(args.config)
    init_db(settings.db_path)
    store = Store(settings.db_path)
    try:
        apply_seed(store, settings.agents)
    finally:
        store.close()
    print(f"Initialized DB at {settings.db_path} with {len(settings.agents)} agent(s):")
    for agent in settings.agents:
        print(f"  - {agent.agent_id} ({agent.mailbox}) enabled={agent.enabled}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    settings = load_config(args.config)
    missing = missing_secrets(settings)
    if missing:
        print("Cannot start: these mailbox password environment variables are not set:")
        for name in missing:
            print(f"  - {name}")
        print("Set them (e.g. via your .env) and reload your shell, then retry `run`.")
        return 2
    print(f"Starting SAFI live loop for {len(settings.agents)} agent(s); "
          f"llm_mode={settings.llm_mode}. Press Ctrl+C to stop.")
    service.run(settings)
    print("Stopped.")
    return 0


def _demo_agent(agent_id: str, name: str, mailbox: str, training: list[str]) -> AgentConfig:
    return AgentConfig(
        agent_id=agent_id,
        name=name,
        mailbox=mailbox,
        model="fake-model",
        enabled=True,
        private_senders=["owner@example.com"],
        seed_training=training,
    )


def _cmd_demo(_args: argparse.Namespace) -> int:
    """Offline, no-credentials end-to-end proof. See module docstring."""
    db_path = "./data/demo.sqlite"
    files_dir = "./data/demo_files"
    logger = get_logger("safi.demo")

    store = Store(db_path)
    llm = FakeLlmClient()
    transport = InMemoryTransport()

    # Two agents with DIFFERENT training so their replies must differ (doc §18/§31).
    keeper = _demo_agent(
        "email-keeper", "Email Keeper", "email-keeper@example.com",
        ["Always sign off with 'Warm regards, Email Keeper'."],
    )
    scheduler = _demo_agent(
        "schedule-keeper", "Schedule Keeper", "schedule-keeper@example.com",
        ["Always propose meeting times only within business hours, Mon-Fri 9am-5pm."],
    )
    apply_seed(store, [keeper, scheduler])

    owner = "owner@example.com"
    client = "client@example.com"

    print("=== Step (a): authorized Private training to each agent ===")
    for agent, note in (
        (keeper, "When replying to invoices, always mention our Net 30 payment term."),
        (scheduler, "Always confirm timezone explicitly before finalizing a meeting."),
    ):
        raw = compose.make_message(
            sender=owner, to=agent.mailbox, subject="Private", body=note,
        )
        transport.deliver(agent.mailbox, raw)
        records = service.poll_agent_once(
            store, agent, llm, transport, files_dir=files_dir, logger=logger,
        )
        print(f"  {agent.agent_id}: {records}")

    print("=== Step (b): the SAME ordinary work email to both agents ===")
    same_subject = "Contract Renewal"
    same_body = "Hi, can you help us move forward with the contract renewal?"
    for agent in (keeper, scheduler):
        raw = compose.make_message(sender=client, to=agent.mailbox, subject=same_subject,
                                    body=same_body)
        transport.deliver(agent.mailbox, raw)
        records = service.poll_agent_once(
            store, agent, llm, transport, files_dir=files_dir, logger=logger,
        )
        print(f"  {agent.agent_id}: {records}")

    print("=== Step (c): each agent's reply from transport.sent ===")
    keeper_replies = [m for m in transport.sent_to(client) if m["from"] == keeper.mailbox]
    scheduler_replies = [m for m in transport.sent_to(client) if m["from"] == scheduler.mailbox]

    if not keeper_replies or not scheduler_replies:
        raise RuntimeError("demo failed: expected one reply from each agent to the client")

    keeper_body = keeper_replies[-1]["body"]
    scheduler_body = scheduler_replies[-1]["body"]

    print(f"\n[email-keeper reply]\n{keeper_body}\n")
    print(f"[schedule-keeper reply]\n{scheduler_body}\n")

    if keeper_body == scheduler_body:
        raise RuntimeError(
            "demo failed: both agents produced identical replies; training did not "
            "differentiate behaviour (doc §18/§31)"
        )

    store.close()
    print("DEMO OK")
    return 0


def _cmd_api(args: argparse.Namespace) -> int:
    import uvicorn  # lazy: only required when serving the HTTP API

    from .api import create_app

    settings = load_config(args.config)
    app = create_app(settings)
    print(f"Starting SAFI HTTP API at http://{args.host}:{args.port} "
          f"(multi_tenant={settings.multi_tenant}, llm_mode={settings.llm_mode}).")
    print(f"Interactive OpenAPI docs: http://{args.host}:{args.port}/docs")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="safi", description="SAFI Product 009 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-db", help="Initialize the DB and seed agents from config")
    p_init.add_argument("--config", default="agents.yaml")
    p_init.set_defaults(func=_cmd_init_db)

    p_run = sub.add_parser("run", help="Run the live IMAP/SMTP polling loop")
    p_run.add_argument("--config", default="agents.yaml")
    p_run.set_defaults(func=_cmd_run)

    p_demo = sub.add_parser("demo", help="Offline, credential-free end-to-end demo")
    p_demo.set_defaults(func=_cmd_demo)

    p_api = sub.add_parser("api", help="Run the HTTP API (FastAPI) for external callers")
    p_api.add_argument("--config", default="agents.yaml")
    p_api.add_argument("--host", default="127.0.0.1")
    p_api.add_argument("--port", type=int, default=8000)
    p_api.set_defaults(func=_cmd_api)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
