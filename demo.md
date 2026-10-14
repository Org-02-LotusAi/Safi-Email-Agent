# demo.md — What SAFI Is, What It Does, and How to Run It

A plain-language walkthrough of the product: what it is, real use cases, how to run it (both a
zero-setup offline demo and the live version), and what to expect. If you only read one doc
before showing this to someone, read this one.

---

## What this project basically is

**SAFI is an AI worker you talk to over ordinary email.** You give it an email address, you
train it by emailing it instructions, and then people email it work and it emails back
useful, contextual replies.

The trick: there is **one generic program**. It has no idea what "an email keeper" or "a
scheduler" is. An agent *becomes* one because of how you **train** it — not because anyone
wrote special code. Train two mailboxes differently and you have two different assistants
running the exact same code.

> Buy a Trainable Agent → train it privately by email → send it work by email → get
> genuinely contextual answers back. No custom software per assistant.

## How it works, in one picture

```
Someone emails  ──▶  the agent's mailbox  ──▶  SAFI service
                                                 │  is the subject "Private"?
                                                 │    yes → OWNER is training it  (learn)
                                                 │    no  → a customer task       (do work)
                                                 │  gather: training + this client's history
                                                 │          + this email + forwarded text + attachments
                                                 │  ask the AI (a fresh session each time)
                                                 └──▶  emails the reply back
```

## Two kinds of email it understands

1. **Ordinary work email** (any subject): a task. The agent reads it (plus any forwarded
   history and TXT/PDF/DOCX attachments), and replies. Each sender is a separate "client" with
   their own remembered context per subject.
2. **`Subject: Private`** (from an authorized owner only): training. You teach it in plain
   English — rules, facts, preferences, examples, or attach a reference document. It replies
   with a short "got it," and every future reply follows your guidance. People who aren't
   authorized can't train it.

## Real use cases

- **Reply Assistant** — forward it a customer thread and say "draft a good reply." It uses the
  forwarded history and your house rules (e.g. "always mention Net 30 terms," "keep it
  concise," "never quote pricing unless asked").
- **Schedule Assistant** — trained to "only propose Mon–Fri 9–5 and always confirm timezone."
  Customers email it to set up calls; it answers within your rules.
- **Proposal / product-info responder** — attach your product sheet once via `Private`; from
  then on it answers customer questions using that document without you re-attaching it.
- **Any specialized correspondent** — the same code, trained differently per mailbox.

What it will **not** do (by design): spend money, sign contracts, change calendars, or touch
other systems. It only reads its mailbox and sends email replies.

---

## Run it — Option A: offline demo (no accounts, 30 seconds)

Proves the whole idea on your laptop with zero setup:

```bash
cd newSafi
python -m pip install -r requirements.txt
python -m safi demo
```

**What you'll see:** two agents get trained differently, both receive the *same* email, and
they print two *different* replies — then `DEMO OK`. That's the core proof: specialization from
training alone, no code change.

Run the full test suite (all 22 acceptance criteria from the spec + unit tests):
```bash
python -m pytest -q        # 55 passed
```

## Run it — Option B: live over real email

You need two email accounts (e.g. two free Gmail accounts) and an Anthropic API key. The full
step-by-step — creating the accounts, enabling IMAP, generating app passwords — is in
**[requirements.md](requirements.md)**. Once configured:

```bash
# after editing agents.yaml + .env (see requirements.md)
# load .env into your shell, then:
python -m safi init-db --config agents.yaml
python -m safi run     --config agents.yaml
```

`run` keeps a live connection to each mailbox and processes mail as it arrives (Ctrl+C to
stop). It refuses to start with a clear message if a password isn't loaded.

### Try it live (once `run` is going)
1. From any email, send a short message to an agent's address → you get a reply back.
2. From your **owner** address, send `Subject: Private` with an instruction like *"Always sign
   off as 'The Team'."* → you get a short acknowledgement, and the next reply follows it.
3. Train your two agents differently and send them the same email → the replies differ.

---

## Who can train it (the "Private" model — read this)

Training is an **owner** function, on purpose. Only the email addresses you list under each
agent's `private_senders` can teach it via `Subject: Private`; everyone else can only send it
work. This keeps a random sender from silently changing how the agent behaves for everyone.

- **Every customer already gets their own isolated memory** per (sender, subject) — Alice's
  "Contract Renewal" thread never mixes with Bob's.
- **To let several people train one agent:** add their emails to `private_senders`.
- **To give each person their own trainable agent:** create one mailbox + config block per
  person, with that person as the sole authorized trainer. Same code, provisioned by you.
- **Fully self-service, "email us and auto-get your own trainable agent"** is a *different,
  larger product* (multi-tenant seats/identity) and is intentionally out of scope here (spec
  §43). It's a natural future step.

---

## What to expect / good to know

- **Speed:** a live reply takes a few seconds (it's a real AI call per email).
- **Memory:** training and per-conversation context are saved in a local database
  (`data/safi.sqlite`) and survive restarts. Back this file up — it's the agents' brain.
- **Safety & robustness:** duplicate emails aren't answered twice; one bad email or an AI
  outage won't stop the service; passwords and private training are never written to logs.
- **Deliverability:** brand-new email accounts sometimes land in spam at first. For production
  use a real domain with SPF/DKIM set up. This is an email-provider setting, not the app.
- **Cost:** each work email = one AI call. Watch your Anthropic usage if volume grows.

## The docs, at a glance

| File | For |
|------|-----|
| **demo.md** (this) | What it is, use cases, how to run — start here. |
| **requirements.md** | Get everything from scratch (create accounts, keys) and go live. |
| **working.md** | Full operational manual + troubleshooting. |
| **explain.md** | The "why" behind the design + a client-demo script. |
| **README.md** | Technical overview and architecture. |
