# working.md — Operational Manual

How to install, configure, run, train, and operate the SAFI Trainable Agent Service, and
exactly what to expect at each step. If README.md is the overview and explain.md is the
"why," this is the "how."

---

## 0. Prerequisites

- **Python 3.11+** (developed and tested on 3.14).
- For **live** operation: at least two ordinary hosted mailboxes that support IMAP + SMTP
  client access, and an Anthropic API key.
- For the **offline demo and tests**: nothing but Python and the dependencies below — no
  mailboxes, no API key.

```bash
python -m pip install -r requirements.txt        # runtime (pypdf, python-docx, PyYAML, anthropic)
python -m pip install -r requirements-dev.txt    # adds pytest, fpdf2 for the test suite
```

---

## 1. Prove it works in 30 seconds (offline, no credentials)

```bash
python -m safi demo
```

**What to expect:** a printed walkthrough with three steps — (a) two agents receive private
training, (b) both receive the *same* "Contract Renewal" email, (c) each agent's reply is
printed. The two replies differ (one reflects payment-term training, the other scheduling
training), and the run ends with:

```
DEMO OK
```

If you see `DEMO OK`, the whole pipeline — parsing, canonicalization, private training,
context assembly, micro-session, persistence, and reply — is working.

### Run the acceptance + unit tests

```bash
python -m pytest -q
```

**What to expect:** `55 passed`. The 22 acceptance tests (`tests/test_acceptance.py`,
`test_t01`–`test_t22`) correspond one-to-one to the specification's acceptance tests (§40).
To run just the acceptance suite: `python -m pytest tests/test_acceptance.py -v`.

---

## 2. Configure real agents

1. **Copy the templates:**
   ```bash
   cp agents.example.yaml agents.yaml
   cp .env.example .env
   ```
2. **Edit `agents.yaml`:** for each agent set `mailbox`, `private_senders` (the addresses
   allowed to train it), the `imap`/`smtp` server settings, and optionally `seed_training`
   (bootstrap rules applied once). Each agent references its passwords by **environment
   variable name** via `password_env:` — never paste passwords into the YAML.
3. **Edit `.env`:** set `ANTHROPIC_API_KEY`, the per-agent IMAP/SMTP password variables named
   in your YAML (e.g. `REPLY_AGENT_IMAP_PASSWORD`), and optionally `SAFI_LLM` (`anthropic` or
   `fake`). Set the model per agent (`model:`) or `default_model:` to a valid model id for
   your account.
4. **Load `.env` into your shell** (it is not read automatically). On PowerShell:
   ```powershell
   Get-Content .env | ForEach-Object { if ($_ -match '^\s*([^#=]+)=(.*)$') { Set-Item "Env:$($matches[1].Trim())" $matches[2].Trim() } }
   ```
   On bash: `set -a; . ./.env; set +a`

> **Security:** `.env` and `data/*.sqlite` are git-ignored. Passwords and API keys never
> appear in config files, logs, or the database (§38).

---

## 3. Initialize and run

```bash
python -m safi init-db --config agents.yaml   # create schema + seed agents (idempotent)
python -m safi run     --config agents.yaml   # start the live loop; Ctrl+C to stop
```

**What to expect from `init-db`:** a summary listing each agent id, mailbox, and enabled
state. Safe to re-run; it will not duplicate seed training.

**What to expect from `run`:** a start line, then the service connects to each agent's
mailbox and waits for mail using **IMAP IDLE** (falling back to periodic polling every
`poll_interval` seconds if IDLE is unavailable). Each processed message emits one JSON log
line. `Ctrl+C` stops cleanly.

---

## 4. Using an agent (what the end user does)

### Send it ordinary work
Email the agent's mailbox with any normal subject and body. Attach TXT/PDF/DOCX if relevant,
or forward a prior conversation. **Expect:** a normal email reply from the agent's mailbox,
threaded under `Re: <your subject>`, reflecting your attachments/forwarded content and any
prior context on that subject.

### Train it (owner only)
From an **authorized** address, email the agent with the subject exactly **`Private`** and
write your instruction in plain language, e.g.:

```
Subject: Private

When replying to customers, keep replies concise.
Do not discuss pricing unless the customer asks.
The attached document is our current product description.
```

Attach a reference document if you want it remembered permanently. **Expect:** a concise
acknowledgement email (it will *not* echo your full instruction back), and the new guidance
takes effect on the next work email. From an **unauthorized** address, a `Private` email
changes nothing and is logged (and, under the default `reject` policy, gets a short "not
authorized" reply).

### What the agent will and won't do
It reads its own mailbox, uses the context you give it, and drafts/sends email replies. It
will **not** make purchases, sign contracts, change calendars, or touch other systems (§32).

---

## 5. Behaviour reference — what to expect in edge cases

| Situation | Behaviour |
|-----------|-----------|
| `Re:`/`Fwd:` prefixes, odd casing/spacing on the subject | Normalized to the same Canonical Subject, so the thread stays in one context. (§14) |
| Same subject from two different senders | Kept as **separate** client contexts. (§4) |
| Same sender, two different subjects | Kept as **separate** subject contexts. (§5) |
| Forwarded email / quoted history in the body | Treated as dynamic context for this reply. (§22) |
| Unsupported attachment (e.g. `.zip`) | Ignored; the agent still replies and records it as unsupported — no crash. (§24, §37) |
| The same email is delivered twice (IMAP redelivery) | Processed once; the duplicate is detected and skipped. (§36) |
| The LLM call fails or times out | Logged as a controlled failure; the message is left unprocessed (so it can be retried) and the service keeps handling other mail. (§37) |
| Service restart | Training and per-subject context persist in SQLite and are used again. (§22) |
| A private instruction relevant to a customer request | Applied as the agent's own policy; the private message itself is never quoted to the customer. (§12, §30) |

---

## 6. Where things live

| Path | Contents |
|------|----------|
| `agents.yaml` | Your agent definitions (from `agents.example.yaml`). |
| `.env` | Secrets: API key + mailbox passwords (git-ignored). |
| `data/safi.sqlite` | All persistent state: agents, private senders, training, file metadata, (client,subject) summaries, micro-session log, processed-message dedup table (§35). |
| `data/files/` | Stored reference-document bytes from authorized `Private` attachments. |
| stdout | One JSON log line per processed message: timestamp, agent_id, message id, sender, canonical subject, message_class (`PRIVATE`/`WORK`), micro_session_id, result, latency_ms (§38). |

### Inspecting state
```bash
sqlite3 data/safi.sqlite ".tables"
sqlite3 data/safi.sqlite "SELECT category, content FROM training;"
sqlite3 data/safi.sqlite "SELECT client_id, canonical_subject, summary FROM subject_context;"
sqlite3 data/safi.sqlite "SELECT agent_id, canonical_subject, result_summary FROM micro_sessions;"
```

---

## 7. Adding a third agent (no code change)

1. Add a new entry under `agents:` in `agents.yaml` (new `agent_id`, `mailbox`,
   `private_senders`, optional `seed_training`, and its `imap`/`smtp` blocks).
2. Add its password env vars to `.env` and reload.
3. `python -m safi init-db --config agents.yaml` then `python -m safi run`.
4. Train it by email. It runs the same generic code as every other agent (§9 build step,
   §44).

---

## 8. Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `python -m safi run` can't connect | IMAP/SMTP host/port/credentials wrong, or `.env` not loaded into the shell. Verify with your provider's client settings. |
| Agent doesn't reply to a `Private` email | Sender address not in that agent's `private_senders`, or subject wasn't exactly `Private` (case-insensitive, prefixes stripped). |
| Replies ignore training | Confirm the training was sent from an authorized address and acknowledged; check `SELECT * FROM training;`. |
| Live LLM errors | Ensure `ANTHROPIC_API_KEY` is set and `model:` is a valid model id for your account; or set `SAFI_LLM=fake` to run without the model. |
| Want to reset an agent | Stop the service and delete `data/safi.sqlite` (and `data/files/`) to start clean, then `init-db` again. |
| Tests can't import `conftest` | Run pytest from the project root (`python -m pytest`), not from inside `tests/`. |
