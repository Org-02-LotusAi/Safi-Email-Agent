# SAFI Product 009 — Trainable Agent Service with Email Interface

A **use-case-neutral** Python service that runs multiple **Trainable Agents**. Each agent
owns an ordinary email mailbox, is trained entirely through email (no code changes), and
replies through ordinary email. Two agents run the *same code* and become specialised —
"Email Keeper", "Schedule Keeper", "Proposal Writer", … — purely through their training,
persistent context, reference files, and operating rules.

> One generic codebase. Many specialised agents. Configuration and training, never custom
> application code. — *Product 009, §2.*

---

## What it does

- **Email is the interface.** An agent receives tasks as ordinary email (IMAP), and replies
  as ordinary email (SMTP), preserving normal threading (`In-Reply-To` / `References`).
- **Trainable by email.** A reserved `Subject: Private` control channel lets *authorized*
  senders teach the agent in natural language — instructions, facts, preferences, examples,
  corrections, operating rules, and reference documents. No special syntax required.
- **Contextual answers.** Every task runs in a **fresh micro-session** assembled from four
  layers: Agent Training → Client context → (Client, Canonical Subject) context → Dynamic
  context (the current email, forwarded history, and attachments).
- **Reads documents.** TXT, PDF, and DOCX attachments are parsed and used as context;
  unsupported types are ignored without crashing.
- **Remembers what matters.** Compact per-(Client, Subject) summaries persist in SQLite and
  survive restarts. The LLM conversation is *not* the memory — the service owns the state.
- **Safe by construction.** Private training is isolated (never quoted back to third
  parties), unauthorized senders cannot train the agent, duplicate emails never execute
  twice, and one bad email never stops the service.

## Architecture

```
Ordinary Email ──▶ Agent Mailbox ──▶ Trainable Agent Service
                                        ├─ identify Agent (by mailbox)
                                        ├─ identify Client (by sender)
                                        ├─ canonicalize Subject
                                        ├─ Subject == "Private"?
                                        │     ├─ yes ▶ PRIVATE control plane (train)
                                        │     └─ no  ▶ NORMAL work plane
                                        ├─ load training + (Client,Subject) context
                                        ├─ ingest forwarded email + attachments
                                        ├─ start FRESH micro-session ▶ LLM
                                        └─ persist permitted result ──▶ Email Reply
```

The service is deliberately built around two small interfaces so the exact same logic runs
live or fully offline:

| Interface | Live implementation | Offline implementation (tests + demo) |
|-----------|---------------------|----------------------------------------|
| `MailTransport` | `ImapSmtpTransport` (IMAP IDLE + SMTP) | `InMemoryTransport` |
| `LlmClient` | `AnthropicClient` (Claude) | `FakeLlmClient` (deterministic simulator) |

### Modules (`safi/`)
`models` · `subject` (canonicalization) · `db` (SQLite) · `attachments` (TXT/PDF/DOCX) ·
`email_parse` · `context` (context engine) · `llm` · `private_channel` · `agent_runtime`
(micro-session) · `transport` · `service` (orchestrator) · `config` · `logging_setup` ·
`cli`.

## Quick start

```bash
# 1. Install
python -m pip install -r requirements.txt          # runtime
python -m pip install -r requirements-dev.txt       # + test deps

# 2. See it work end-to-end with NO credentials (offline demo)
python -m safi demo

# 3. Run the full acceptance + unit test suite
python -m pytest -q
```

The offline demo trains two agents differently, sends them the *same* email, and prints
two *different* replies — the core proof of Product 009 — ending in `DEMO OK`.

## HTTP API + multi-tenant mode (beyond the Product 009 SOW)

In addition to the email interface, SAFI exposes an **HTTP API** (FastAPI) so an external
platform (e.g. a meeting manager) can call it, and supports **multi-tenant isolation**: every
distinct `user` gets their own private instance of an agent — their own training and memory —
isolated from everyone else (instance id `"{agent}::{user}"`). This intentionally extends past
the 009 SOW (§43); it is gated by `multi_tenant: true` in `agents.yaml`, and the original
single-tenant, SOW-compliant behavior remains available (`multi_tenant: false`) and is still
covered by the 22 acceptance tests.

```bash
# offline trial, no key:
SAFI_LLM=fake python -m safi api --config agents.yaml --port 8000
# then open http://127.0.0.1:8000/docs  (interactive OpenAPI docs)

curl -X POST http://127.0.0.1:8000/v1/agents/schedule-agent/messages \
  -H "Content-Type: application/json" \
  -d '{"user":"alice@corp.com","subject":"Meeting request","body":"Can we meet next week?"}'
```

Endpoints: `GET /health`, `GET /v1/agents`, `POST /v1/agents/{agent}/messages` (subject
`Private` trains that user's instance; otherwise it's work), `GET /v1/agents/{agent}/users/{user}`
(inspect), `DELETE /v1/agents/{agent}/users/{user}` (reset). Optional `X-API-Key` auth via the
`SAFI_API_KEY` env var. Full walkthrough: **[instruction.md](instruction.md)**.

## Running against real mailboxes

```bash
cp agents.example.yaml agents.yaml     # edit mailboxes & authorized senders
cp .env.example .env                   # set ANTHROPIC_API_KEY + IMAP/SMTP passwords
# load .env into your shell, then:
python -m safi init-db --config agents.yaml
python -m safi run     --config agents.yaml
```

Secrets live only in environment variables referenced by `password_env:` in the YAML — never
in the config file or git. See **[working.md](working.md)** for the full operational manual
and **[explain.md](explain.md)** for the product rationale and a demo script.

## Configuration model

Two agents differ only by their YAML entry + accumulated training:

```yaml
agents:
  - agent_id: reply-agent
    mailbox: reply-agent@example.com
    private_senders: [owner@example.com]
    seed_training: ["Always reply concisely and professionally."]
    imap: {host: imap.example.com, port: 993, user: ..., password_env: REPLY_AGENT_IMAP_PASSWORD, ssl: true}
    smtp: {host: smtp.example.com, port: 587, user: ..., password_env: REPLY_AGENT_SMTP_PASSWORD, starttls: true}
```

## Test coverage

`python -m pytest -q` runs **55 tests**, including all **22 objective acceptance tests**
from the specification (§40), one per `test_tNN_*` in `tests/test_acceptance.py`:

| # | Acceptance test | # | Acceptance test |
|---|-----------------|---|-----------------|
| 01 | Ordinary email reception | 12 | PDF attachment context |
| 02 | Ordinary email reply | 13 | DOCX attachment context |
| 03 | Subject canonicalization | 14 | Private reference file |
| 04 | Client separation | 15 | Fresh micro-session |
| 05 | Subject separation | 16 | Persistent subject context |
| 06 | Private authorized sender | 17 | No cross-subject leakage |
| 07 | Private unauthorized sender | 18 | Two differently trained agents |
| 08 | Private is not work | 19 | Duplicate message |
| 09 | Training changes behavior | 20 | LLM failure |
| 10 | Private content not exposed | 21 | Unsupported attachment |
| 11 | Forwarded email context | 22 | Restart persistence |

## Scope

**In scope:** ordinary IMAP/SMTP mailboxes, the Private training channel with sender
allowlisting, the four-layer context engine, fresh micro-sessions, TXT/PDF/DOCX ingestion,
SQLite persistence, and duplicate/failure handling.

**Out of scope (by design, §43):** self-hosted mail server, Amazon SES, Gmail/Outlook-specific
APIs, webmail UI, agent marketplace, billing, calendar/CRM integration, vector databases,
multi-agent-on-one-mailbox routing, agent-to-agent workflows, and foundation-model
fine-tuning.

## Requirements

Python ≥ 3.11 (developed on 3.14). Runtime deps: `pypdf`, `python-docx`, `PyYAML`, and
`anthropic` (imported lazily — not needed for the offline demo or tests).
