# explain.md — The "Why" Behind Product 009 (Demo Preparation)

This document is your briefing for demoing SAFI Product 009 to a client. It explains what
the product *is*, the problem it solves, why each design decision was made, and gives you a
ready-to-run demo script with talking points and likely questions.

---

## 1. The one-sentence pitch

> **A customer can buy a Trainable Agent, train it privately through email, send it ordinary
> work by email, give it context through forwarded messages and attachments, and receive
> genuinely contextual results — without anyone writing custom software for that agent.**

That last clause is the whole product. Everything else is in service of it.

## 2. The problem it solves

Businesses want AI "workers" that behave like a specialised assistant (a proposal writer, a
scheduler, an email keeper). The naive way to build these is to write bespoke code for each
one. That doesn't scale: every new agent type is an engineering project, and every change to
an agent's behaviour is a code deploy.

Product 009 flips this. There is **one** generic program. A new agent is created by giving it
a mailbox and *training it by email*. Changing its behaviour is sending it another email.
Non-engineers can create and steer agents. That is what makes a Trainable Agent **sellable**.

## 3. The core idea: specialization without code

The single most important thing to convey in a demo:

- **The application code is use-case-neutral.** It knows nothing about "email keeping" or
  "scheduling." (§2)
- An agent becomes an *Email Keeper* or a *Schedule Keeper* only because of its **Training
  Package + persistent context + reference files + operating rules**. (§7)
- **Proof:** send the *same* email to two differently trained agents and get two
  appropriately different replies — with **zero** code differences between them. (§18, §31)

The offline `python -m safi demo` demonstrates exactly this in ~2 seconds.

## 4. Why each big decision was made

| Decision | Why (per the spec) |
|----------|--------------------|
| **Email is the interface** | Every business already has email. No new app to learn, no portal to log into, no integration to build. The agent is "just another colleague with an email address." (§1, §45) |
| **Ordinary IMAP/SMTP, not a mail server or SES** | The product must run on *any* hosted mailbox and never become mail infrastructure. This keeps it deployable anywhere and vendor-neutral. (§5, §43) |
| **`Subject: Private` is a reserved control channel** | Training and doing work must be cleanly separated. "Private" is how the owner steers the agent; everything else is customer work. A reserved subject makes that boundary explicit and unmistakable. (§9, §16) |
| **Only allowlisted senders can train** | Training changes the agent's behaviour for *everyone*. So only authorized addresses may use `Private`; anyone else is ignored and logged. (§10, §11) |
| **Private content is isolated** | The owner's private instructions may *shape* replies but must never be quoted or leaked to customers. The agent applies the rule as its own policy. (§12, §30) |
| **Context is namespaced by (Client, Subject)** | So Alice's "Contract Renewal" thread never bleeds into Bob's, and Alice's "Scheduling" never bleeds into her "Contract Renewal." Each conversation stays coherent and separate. (§15, §17) |
| **Fresh micro-session per task** | The AI conversation is *disposable*; the durable memory is the service's own database. This makes behaviour reproducible, auditable, and restart-safe — not dependent on an ever-growing chat window. (§18, §19, §28) |
| **Compact summaries, not raw dumps** | Persisting every raw prompt would be expensive, leaky, and noisy. Only compact, relevant context is kept. (§28, §29) |
| **No dangerous actions** | The agent reads its mailbox, uses context, and drafts/sends *its own* replies. It cannot make purchases, sign contracts, or touch other systems. This is a contextual-reply product, not an autonomous actuator. (§32) |

## 5. The four layers of context (say this slowly in a demo)

Every reply is assembled from, in order of specificity:

1. **Agent Training** — who the agent is and its rules (from `Private` emails).
2. **Client context** — who it's talking to (the sender is the client identity).
3. **(Client, Subject) context** — the running summary of *this* conversation.
4. **Dynamic context** — the current email, any forwarded history, and any attachments.

The agent never dumps "everything it knows" — it pulls only what's relevant to *this* client
and *this* subject. That's what makes the replies feel intelligent rather than generic.

## 6. Suggested live demo script (≈5 minutes)

> Run `python -m safi demo` once beforehand so the audience sees the payoff immediately, then
> walk through *why* it happened.

1. **"One program, two workers."** Show the two agents in `agents.example.yaml`. Point out
   they share the identical codebase; only the YAML entry and training differ.
2. **"Train by email."** Show a `Subject: Private` message: *"Always mention our Net 30
   payment term."* Explain that only the owner's address can do this.
3. **"Same question, different answers."** Show the demo output: both agents got the same
   "Contract Renewal" email; the Email Keeper mentions the payment term, the Schedule Keeper
   talks about business hours. **No code changed between them.**
4. **"It reads your documents."** Mention TXT/PDF/DOCX: forward a PDF of your terms and the
   reply reflects it (acceptance tests T12/T13 prove this).
5. **"It's safe."** The owner's private note about pricing shaped the reply, but the private
   message itself was never quoted to the customer (T10). Unauthorized people can't train it
   (T07). Duplicate emails don't double-execute (T19). A model outage doesn't stop the
   service (T20).
6. **"It remembers."** Come back tomorrow on the same subject and it recalls the thread —
   even after a restart (T16, T22).

## 7. Questions a client will likely ask — and honest answers

- **"Which email providers work?"** Any provider offering ordinary IMAP + SMTP client access.
  We are not tied to Gmail or Outlook APIs. (§5, §43)
- **"Where does the data live?"** In a local SQLite database and a files folder you control.
  No third-party document platform. (§5, §35)
- **"Can it send money / sign things / edit my calendar?"** No — by design. It only reads its
  mailbox and drafts/sends email replies. (§32)
- **"How is training different from fine-tuning?"** Training here means instructions, facts,
  preferences, examples, and reference docs stored by the service — *not* retraining the
  underlying model. Changes take effect on the very next email. (§6)
- **"What if two people email at once / the model is down / an email is resent?"** Each is
  handled explicitly: separate contexts, controlled failures that don't stop the service, and
  duplicate detection. (§36, §37)
- **"Can I add a third agent?"** Yes — add a mailbox and a YAML entry, then train it. No code
  change, no deploy of new logic. (§9 of the build steps, §44)

## 8. What "done" means (so you can speak to it confidently)

The specification lists 22 objective PASS/FAIL acceptance tests and a Definition of Done
(§44). **All 22 are implemented as automated tests and pass** (`tests/test_acceptance.py`),
alongside unit tests — 55 tests total. The offline demo provides a credential-free,
repeatable proof you can run on any laptop in front of a client.
