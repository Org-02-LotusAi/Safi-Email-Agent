# SAFI Product 009 — Trainable Agent Service — Implementation Plan

Source of truth: `Document from Jaithra Sarma.docx` (extracted to `_doc_extracted.txt`).
This plan does not add scope beyond the doc. Anything not in the doc is out of scope (§43).

## Objective (doc §1, §44, §45)
One use-case-neutral Python service. Multiple **Trainable Agents**, each with its own
ordinary email mailbox (IMAP/SMTP). Agents receive tasks by ordinary email, are trained
via a reserved `Subject: Private` control channel (authorized senders only), ingest
forwarded email + TXT/PDF/DOCX attachments, run a **fresh LLM micro-session** per task
assembled from Training + Client + (Client,Subject) + Dynamic context, reply by email,
and persist compact state in SQLite. ≥2 agents differ only by config/training — no code
difference. All 22 acceptance tests (§40) pass. Survives restart.

## Global constraints (frozen — doc §6, §43)
- Language: **Python**. Persistence: **SQLite**. Mail: ordinary **IMAP/IMAP-IDLE + SMTP**.
- Attachments MUST support: **TXT, PDF, DOCX**. Unsupported types must NOT crash (§24, §37).
- One configured **LLM endpoint** (Anthropic Claude by default; pluggable).
- NOT allowed: own mail server, Amazon SES mailbox, Gmail-specific or Outlook-specific
  API dependency, webmail UI, marketplace, billing, calendar/CRM, vector DB, multi-agent
  routing on one mailbox, agent-to-agent workflows, foundation-model fine-tuning.
- `Private` is a **reserved canonical subject** = control plane; never ordinary work (§9, §16).
- Persistent namespace = **(Client, Canonical Subject)** (§15). No cross-subject/client leakage.
- Persistent memory belongs to the Service, not an open LLM session (§18, §28).
- No dangerous external actions — only read own mailbox, use context, draft/send its own
  email replies (§32).
- Do not log passwords, API keys, full private attachments, or raw private training (§38).

## Key architectural decision (makes it a *testable, runnable* tool)
`MailTransport` and `LlmClient` are interfaces with two implementations each:
1. **Live**: `ImapSmtpTransport` (imaplib IDLE + smtplib) and `AnthropicClient`.
2. **Offline**: `InMemoryTransport` and `FakeLlmClient` (deterministic instruction-following
   simulator that makes context routing observable).
Same generic runtime code drives both. All 22 acceptance tests run offline (no credentials);
the identical code path runs live when `agents.yaml` + env secrets are provided.

## Modules (frozen interfaces)
- `safi/models.py` — dataclasses: `AgentConfig`, `ParsedAttachment`, `IncomingEmail`,
  `MicroSessionResult`.
- `safi/subject.py` — `canonicalize_subject(raw)->str` (strip Re:/RE:/Fwd:/FW: chain,
  collapse ws, keep case), `subject_key(c)->str` (casefold), `is_private_subject(c)->bool`,
  `reply_subject(c)->str` (one `Re: ` prefix).  [TEST 3]
- `safi/attachments.py` — `extract(filename, data)->ParsedAttachment` for .txt/.pdf/.docx
  (+ .eml best-effort); unsupported -> supported=False, no raise; errors captured. [12,13,21]
- `safi/email_parse.py` — `parse_email(raw_bytes, delivered_to)->IncomingEmail`: Message-ID,
  From (normalized lower), Subject->canonical, In-Reply-To/References/thread_key, text body,
  forwarded/quoted text extraction, attachments via walk. [11, threading §23]
- `safi/db.py` — `init_db(path)`, `Store` with agent/private-sender/training/files/
  subject-context/micro-session/processed-message methods. Schema per §35 + `PROCESSED`
  dedup table (§36). WAL.
- `safi/llm.py` — `LlmClient` protocol; `AnthropicClient` (lazy import); `FakeLlmClient`
  (deterministic reflector: applies training directive lines as its own policy, reflects
  dynamic-context FACTS, changes output when training present vs absent, can be forced to
  raise for the failure test). [9,10,18,20]
- `safi/context.py` — `assemble(store, agent, incoming)->(system, user)`: sections =
  Agent role/training + reference files -> (client,subject) summary -> dynamic (current
  email, forwarded, attachments, thread). Only the CURRENT (client,subject) summary is
  injected (no cross-subject/client). [4,5,16,17,29]
- `safi/private_channel.py` — authorize sender; persist NL training + private attachments as
  persistent reference FILES; send concise ack; reject+log unauthorized; never modify state
  on reject; isolation (never echo private source). [6,7,8,10,14,25,27]
- `safi/agent_runtime.py` — `run_micro_session(store, agent, incoming, llm)`: fresh
  micro_session_id, assemble, call llm, persist compact (client,subject) summary, record
  MICRO_SESSIONS row, return result. Use-case-neutral. [15,16,18,39-step1]
- `safi/service.py` — orchestrator: per agent fetch new -> parse -> dedupe -> route
  private/work -> run -> send reply/ack -> mark processed -> log. Per-message try/except so
  one bad email never stops the loop. [1,2,19,20,21,36,37,38]
- `safi/transport.py` — `MailTransport` protocol; `ImapSmtpTransport` (IDLE); `InMemoryTransport`.
- `safi/config.py` — load `agents.yaml`, env secrets by var-name; choose live/fake llm+transport.
- `safi/logging_setup.py` — structured log fields §38; redaction of secrets/private text.
- `safi/cli.py` (`python -m safi`) — `init-db`, `run` (live), `demo` (offline end-to-end).

## Acceptance test map (§40 -> test id)  [all automated offline]
1 reception, 2 reply, 3 canonicalization, 4 client sep, 5 subject sep, 6 private-auth,
7 private-unauth, 8 private-not-work, 9 training-changes-behavior, 10 private-not-exposed,
11 forwarded, 12 pdf, 13 docx, 14 private-reference-file, 15 fresh-micro-session,
16 persistent-subject-context, 17 no-cross-subject-leak, 18 two-agents-differ,
19 duplicate-message, 20 llm-failure, 21 unsupported-attachment, 22 restart-persistence.

## Deliverables (doc §42) + user request
Working service; ≥2 configured agents; Private training; context engine; micro-sessions +
logging; TXT/PDF/DOCX; SQLite schema+init; automated tests; README.md (professional),
explain.md (the "why" of the doc, demo prep), working.md (operational manual). Commit all.

## Build order
1. Scaffold: requirements, package skeleton, pytest config.  2. models+subject+db.
3. attachments+email_parse.  4. llm(fake+anthropic)+context.  5. private_channel+agent_runtime.
6. transport(inmemory+imapsmtp)+service+config+logging.  7. cli+agents.example.yaml.
8. Full test suite (22 acceptance + units).  9. Run suite, triage, fix.  10. Docs. 11. Commit.
