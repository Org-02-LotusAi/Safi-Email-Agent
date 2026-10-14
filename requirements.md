# requirements.md — Zero to Running (Complete Beginner Guide)

You have nothing yet except the code and an Anthropic API key. This guide takes you from
**zero** to **two live agents replying to real email**. Follow it top to bottom. No paid
services are required — we use **two free Gmail accounts**.

**Time needed:** ~30–40 minutes, most of it clicking through Google's security pages.

---

## What you're building

Two email addresses that behave like AI assistants. People email them; the assistants reply.
You (the "owner") train them privately by email. Both run the same code — they differ only by
how you train them.

## The shopping list (all free)

| # | Item | Where it comes from | Cost |
|---|------|--------------------|------|
| 1 | 2 email accounts (the agents) | Create 2 new **Gmail** accounts | Free |
| 2 | IMAP/SMTP turned on + an **app password** for each | Gmail settings (steps below) | Free |
| 3 | Anthropic API key | You already have it | Pay-per-use |
| 4 | A computer to run it on | Your own PC to start | Free |
| 5 | Python 3.11+ | python.org (probably already installed) | Free |
| 6 | An "owner" email (you, the trainer) | Any email you already own | Free |

> Why Gmail? It's free, anyone can create accounts, and its IMAP/SMTP + app-password support is
> the best-documented. If you prefer Outlook/Zoho/etc., the mechanics are identical — see
> "Other providers" at the end.

---

## STEP 1 — Create two new Gmail accounts (the two agents)

Create **two brand-new** Gmail accounts dedicated to the agents. Do **not** use your existing
personal Gmail — these mailboxes are the agents' identities.

1. Open <https://accounts.google.com/signup> (use a private/incognito window so it doesn't
   attach to your current login).
2. Fill in a name and pick an address, e.g. **`yourco.replyagent@gmail.com`**.
3. Set a strong password, complete phone verification if asked, finish setup.
4. Repeat once more for the second agent, e.g. **`yourco.scheduleagent@gmail.com`**.

Write both addresses down. These are `mailbox` #1 and #2.

> Tip: pick clear names like `…replyagent` and `…scheduleagent` so you can tell them apart.

## STEP 2 — For EACH of the two accounts: enable 2FA, IMAP, and an app password

Do this **twice — once per agent account**, while logged into that account.

**2a. Turn on 2-Step Verification** (required before Google will give you an app password)
1. Go to <https://myaccount.google.com/security>.
2. Under "How you sign in to Google" → **2-Step Verification** → turn it **On** (it'll ask for
   a phone number to confirm).

**2b. Enable IMAP in Gmail**
1. Open Gmail for that account → click the **gear** (top right) → **See all settings**.
2. Go to the **Forwarding and POP/IMAP** tab.
3. In the "IMAP access" section, select **Enable IMAP** → **Save Changes** at the bottom.

**2c. Create an app password**
1. Go to <https://myaccount.google.com/apppasswords> (only appears after 2FA is on).
2. Type a name like **`SAFI`** → **Create**.
3. Google shows a **16-character password** (like `abcd efgh ijkl mnop`). **Copy it now** —
   you can't see it again. Remove the spaces when you paste it later.

Repeat 2a–2c for the **second** account. You now have **two 16-character app passwords**, one
per agent. (Gmail's IMAP and SMTP both accept the same app password, so one per account is
enough.)

## STEP 3 — Anthropic API key (you have this)

- If you need to (re)find it: <https://console.anthropic.com> → **API Keys** → **Create Key**.
  It looks like `sk-ant-api03-…`.
- Make sure the workspace has **credits/billing** enabled — live replies call the model and
  cost a small amount per email.
- You'll use model id `claude-sonnet-5` (a good default; you can change it later).

## STEP 4 — A computer to run it on

Your own computer is fine to start. It just needs to **stay on and awake** while the agents are
"working," because the service keeps a live connection to Gmail.

- For a quick demo: run it on your laptop, leave the window open.
- For 24/7: use a small always-on machine or a cheap cloud VM later. (We can set that up
  afterward — not needed to get started.)

## STEP 5 — Install Python 3.11+ (probably already there)

1. Check: open a terminal and run `python --version`. If it says 3.11 or higher, skip this.
2. If not, install from <https://www.python.org/downloads/> (on Windows, tick **"Add Python to
   PATH"** during install).

## STEP 6 — Pick your "owner" address (the trainer)

Choose **one** email you already own (your normal personal/work email). This is the only
address allowed to **train** the agents (by emailing them with `Subject: Private`). Everyone
else can only send them ordinary work. Write it down.

---

## STEP 7 — Configure the tool

Open a terminal in the `newSafi` folder.

```bash
python -m pip install -r requirements.txt      # install dependencies (once)
cp agents.example.yaml agents.yaml             # your config (edit next)
cp .env.example .env                           # your secrets (edit next)
```

**Edit `agents.yaml`.** Replace the placeholder values with your real accounts. For Gmail the
hosts/ports below are already correct — you only change the three highlighted values per agent
(mailbox, user, and the owner address):

```yaml
db_path: ./data/safi.sqlite
files_dir: ./data/files
default_model: claude-sonnet-5
reject_policy: reply
poll_interval: 60

agents:
  - agent_id: reply-agent
    name: Reply Agent
    mailbox: yourco.replyagent@gmail.com          # ← agent account #1
    model: claude-sonnet-5
    private_senders:
      - your-personal@email.com                    # ← YOUR owner address (the trainer)
    imap: { host: imap.gmail.com, port: 993, user: yourco.replyagent@gmail.com, password_env: REPLY_AGENT_IMAP_PASSWORD, ssl: true }
    smtp: { host: smtp.gmail.com, port: 587, user: yourco.replyagent@gmail.com, password_env: REPLY_AGENT_SMTP_PASSWORD, starttls: true }

  - agent_id: schedule-agent
    name: Schedule Agent
    mailbox: yourco.scheduleagent@gmail.com        # ← agent account #2
    model: claude-sonnet-5
    private_senders:
      - your-personal@email.com                    # ← same owner address
    imap: { host: imap.gmail.com, port: 993, user: yourco.scheduleagent@gmail.com, password_env: SCHEDULE_AGENT_IMAP_PASSWORD, ssl: true }
    smtp: { host: smtp.gmail.com, port: 587, user: yourco.scheduleagent@gmail.com, password_env: SCHEDULE_AGENT_SMTP_PASSWORD, starttls: true }
```

**Edit `.env`.** Put the real secrets here (this file is never committed to git). Paste each
app password with the spaces removed:

```
ANTHROPIC_API_KEY=sk-ant-api03-...
REPLY_AGENT_IMAP_PASSWORD=abcdefghijklmnop
REPLY_AGENT_SMTP_PASSWORD=abcdefghijklmnop
SCHEDULE_AGENT_IMAP_PASSWORD=qrstuvwxyzabcdef
SCHEDULE_AGENT_SMTP_PASSWORD=qrstuvwxyzabcdef
```
(IMAP and SMTP passwords are the same per account for Gmail — paste the same value into both.)

---

## STEP 8 — Load your secrets and start

**Load `.env` into your terminal session:**
```powershell
# Windows PowerShell:
Get-Content .env | ForEach-Object { if ($_ -match '^\s*([^#=]+)=(.*)$') { Set-Item "Env:$($matches[1].Trim())" $matches[2].Trim() } }
```
```bash
# macOS/Linux bash:
set -a; . ./.env; set +a
```

**Initialize and run:**
```bash
python -m safi init-db --config agents.yaml     # creates the database + agents
python -m safi run     --config agents.yaml      # starts the agents (Ctrl+C to stop)
```

If a password isn't loaded, `run` stops and tells you exactly which one is missing — just fix
`.env`, reload it, and retry.

---

## STEP 9 — Test it (do this before showing anyone)

Leave `python -m safi run` running, and from a **different** email (e.g. your owner address):

1. **Ordinary work:** send a short email to `yourco.replyagent@gmail.com` with any subject and
   a simple request. Within a few seconds you should get a reply from that address. ✅
2. **Training:** send an email to the same agent with the subject exactly **`Private`** and a
   plain-language instruction, e.g. *"Always sign your emails as 'The Reply Team'."* You should
   get a short "training received" acknowledgement. Then send another ordinary work email — the
   reply should now follow your instruction. ✅
3. **Two agents differ:** send the same email to both agent addresses and (after you've trained
   them differently) watch the replies differ. ✅

If step 1 doesn't produce a reply, see Troubleshooting.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `run` says a password variable is not set | You didn't load `.env` into *this* terminal. Re-run the load command in Step 8, then `run` again. |
| Gmail login fails / "authentication failed" | You used your normal password instead of the **16-char app password**, or 2FA isn't on, or you pasted spaces. Recheck Step 2. |
| No reply arrives | Confirm **IMAP is enabled** in that Gmail account (Step 2b) and the service is still running. Check the terminal for a red error line. |
| Reply lands in spam | Normal for brand-new Gmail senders at first; mark it "not spam" once. For production, use a real domain with SPF/DKIM later. |
| Training ignored | Make sure you sent it from the exact `private_senders` address and the subject was `Private`. |
| Want to start over | Stop the service, delete `data/safi.sqlite` and `data/files/`, then `init-db` again. |

---

## Other providers (if you don't want Gmail)

The only things that change are the hosts/ports and where you generate the app password. Set 2FA
on, find the app-password page, and use these servers:

| Provider | IMAP host / port | SMTP host / port |
|----------|------------------|------------------|
| Outlook.com / Hotmail | `outlook.office365.com` / 993 | `smtp.office365.com` / 587 (STARTTLS) |
| Yahoo Mail | `imap.mail.yahoo.com` / 993 | `smtp.mail.yahoo.com` / 587 |
| iCloud Mail | `imap.mail.me.com` / 993 | `smtp.mail.me.com` / 587 |
| Zoho Mail | `imap.zoho.com` / 993 | `smtp.zoho.com` / 587 |
| Fastmail | `imap.fastmail.com` / 993 | `smtp.fastmail.com` / 587 |

Put those into the `imap:`/`smtp:` `host` and `port` fields in `agents.yaml`; everything else is
the same. (If SMTP is only offered on port **465**, set `starttls: false`.)

---

## What you can ignore for now

Cost caps, custom domains, SPF/DKIM, running 24/7 on a server, log shipping — none of these are
needed to get two agents working and demo-ready. Come back to them once the basics run.

## Recap — the absolute minimum to get running

1. Make **2 free Gmail accounts** (Step 1).
2. For each: **2FA on → Enable IMAP → create an app password** (Step 2).
3. Fill `agents.yaml` (mailboxes + your owner email) and `.env` (Anthropic key + the 2 app
   passwords) (Step 7).
4. Load `.env`, then `init-db`, then `run` (Step 8).
5. Email an agent to confirm it replies (Step 9).
