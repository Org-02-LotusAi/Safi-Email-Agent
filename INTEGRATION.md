# SAFI — Integration Guide for the Meeting-Manager Platform

**Audience:** the engineer integrating SAFI into the meeting-manager platform.
**What SAFI is:** a hosted HTTP service that provides *trainable AI agents*. Your platform sends
a user's message (a scheduling request, an email to draft, etc.) and gets back a contextual
reply. Every one of your users gets their **own private agent instance** — their own training and
memory, isolated from all other users.

You integrate purely over HTTPS/JSON. You do **not** need SAFI's source code, its database, or
any email account — just the four things in §1 and the endpoints in §4.

---

## 0. The button endpoint (your primary integration) — `POST /v1/onboard`

This is the single call your "Get my Safi assistant" button needs. It emails the user their
usage instructions and returns a status so you can show a confirmation message.

Request:
```json
{ "email": "user@corp.com", "name": "Jane" }      // name is optional
```
```bash
curl -X POST {base}/v1/onboard \
  -H "Content-Type: application/json" -H "X-API-Key: KEY" \
  -d '{"email":"user@corp.com","name":"Jane"}'
```
Response `200`:
```json
{"data": {
  "status": "sent",
  "email": "user@corp.com",
  "message": "Instructions have been emailed. Please check your inbox."
}}
```
Button handler logic:
- `200` + `data.status == "sent"` → show the user: **"Check your email — we've sent instructions."**
- `400` → the email was invalid (show "please enter a valid email").
- `401` → your API key is missing/wrong (config issue).
- `502`/`503` → sending failed / not configured (show "couldn't send right now, try again").

The emailed instructions tell the user how to use their assistants (email them, train with
`Subject: Private`, attach docs). After onboarding, they interact by email directly — or your
platform can keep driving them programmatically via the message endpoints in §4.

---

## 1. What you need from the SAFI operator (ask for these)

| Item | Example | Notes |
|------|---------|-------|
| **Base URL** | `https://safi.example.com` (or `http://<ec2-ip>:8000`) | The running EC2 endpoint. Use HTTPS in production. |
| **API key** | `sk_safi_live_…` | Send as header `X-API-Key` on every `/v1/*` call. |
| **Agent IDs** | `reply-agent`, `schedule-agent` | The agents available to call (also from `GET /v1/agents`). |
| **OpenAPI spec** | `openapi.json` (in this repo) / `GET {base}/openapi.json` | Import into Postman/Insomnia or generate a client SDK. |

Interactive docs are live at **`{base}/docs`** (Swagger UI) — you can try every call there.

---

## 2. The one concept that matters: `user` = tenant = isolation key

Every request carries a **`user`** string. SAFI creates/uses a private agent instance per
`(agent, user)` pair, identified as `"{agent}::{user}"`. Two different `user` values can never see
or affect each other's training or memory.

**Use your platform's stable user identity as `user`** — the user's email is ideal (e.g.
`alice@corp.com`). Be consistent: always send the same value for the same person, lower-case
recommended. That's all it takes to give each of your users their own personalized assistant.

---

## 3. Authentication

If the operator set an API key, send it on every `/v1/*` request:
```
X-API-Key: <the key>
```
Missing/wrong key → `401`. `GET /health` needs no key. Keep the key server-side in your backend —
never ship it to browsers/mobile clients. Call SAFI from your platform's backend, not the client.

---

## 4. API reference

Base path `/v1`. All bodies/responses are JSON. Success → `{"data": …}`. Error →
`{"error": {"code","message"}}` (except validation errors, which use FastAPI's `422` `{"detail":…}`).

### `GET /health`  — liveness (no auth)
→ `200 {"status":"ok","version":"0.9.0","multi_tenant":true}`

### `GET /v1/agents`  — list available agents
→ `200 {"data":[{"agent_id":"reply-agent","name":"Reply Agent","mailbox":"…"}, …]}`

### `POST /v1/agents/{agent_id}/messages`  — **the main call**
Send a message as a user; get the agent's reply.

Request:
```json
{
  "user": "alice@corp.com",          // REQUIRED — tenant/isolation key
  "subject": "Meeting request",       // REQUIRED — exact word "Private" = train this user's agent
  "body": "Can we meet next week to discuss the project?",   // REQUIRED
  "attachments": [                    // OPTIONAL — TXT/PDF/DOCX
    {"filename": "terms.pdf", "content_base64": "JVBERi0xLjQ..."}
  ]
}
```
Response `200`:
```json
{"data": {
  "agent_id": "schedule-agent",
  "instance_id": "schedule-agent::alice@corp.com",
  "user": "alice@corp.com",
  "message_class": "WORK",            // "WORK" for tasks, "PRIVATE" for training
  "reply": "…the agent's reply text…",// show this to the user / send it onward
  "status": "work_replied",
  "micro_session_id": "…",
  "training_added": null               // for PRIVATE: number of training items stored
}}
```
- **Normal task:** any `subject` other than `Private` → the agent does the work and `reply` is the
  answer.
- **Train this user's agent:** `subject` exactly `"Private"` → `reply` is a short acknowledgement,
  `message_class` is `"PRIVATE"`, and the instruction in `body` shapes all of this user's future
  replies (only theirs).
- Errors: `404` unknown `agent_id`; `400` malformed base64; `422` missing `user`/`subject`/`body`;
  `401` bad/missing key.

### `GET /v1/agents/{agent_id}/users/{user}`  — inspect a user's instance
→ `200 {"data":{"instance_id":"…","training":[{"category","content","created_at"}…],
"subjects":[{"canonical_subject","summary","updated_at"}…]}}`. Use it to show a user what their
assistant has learned. Unknown-but-valid user → empty lists.

### `DELETE /v1/agents/{agent_id}/users/{user}`  — reset a user's instance
Wipes that user's training + memory. → `200 {"data":{"deleted":{"training":3,…}}}`. Good for an
"unlink / forget me" action.

---

## 5. Integration recipe (what to build)

1. **Pick the tenant key:** map each platform user to a stable `user` (their email).
2. **"Draft a reply" / "set up a meeting" actions:** `POST /v1/agents/reply-agent/messages` or
   `/schedule-agent/messages` with `{user, subject, body}`. Display the returned `reply`.
3. **Personalization screen:** let a user save preferences → `POST …/messages` with
   `subject:"Private"`. Show current knowledge via `GET …/users/{user}`; offer reset via `DELETE`.
4. **Attachments:** base64-encode file bytes; TXT/PDF/DOCX are understood.
5. **Latency:** a real AI reply typically takes a few seconds — call it async / show a spinner;
   use a client timeout of ~60s.
6. **Retries:** retry only on network errors or `5xx`, with backoff. Each POST creates a new unit
   of work, so avoid blindly retrying a `200` (it would produce a second reply).

### Example — Node/TypeScript (your backend)
```ts
const SAFI = "https://safi.example.com";
const KEY = process.env.SAFI_API_KEY!;

async function askAgent(agent: string, user: string, subject: string, body: string) {
  const res = await fetch(`${SAFI}/v1/agents/${agent}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": KEY },
    body: JSON.stringify({ user, subject, body }),
  });
  if (!res.ok) throw new Error(`SAFI ${res.status}: ${await res.text()}`);
  const { data } = await res.json();
  return data.reply as string;
}

// train a user's agent, then use it:
await askAgent("reply-agent", "alice@corp.com", "Private", "Keep replies under 3 sentences.");
const reply = await askAgent("reply-agent", "alice@corp.com", "Follow up", "Draft a thank-you note.");
```

### Example — Python
```python
import requests
SAFI, KEY = "https://safi.example.com", "..."
def ask(agent, user, subject, body):
    r = requests.post(f"{SAFI}/v1/agents/{agent}/messages",
                      headers={"X-API-Key": KEY},
                      json={"user": user, "subject": subject, "body": body}, timeout=60)
    r.raise_for_status()
    return r.json()["data"]["reply"]
```

### Example — curl (smoke test the live box)
```bash
curl {base}/health
curl -H "X-API-Key: KEY" {base}/v1/agents
curl -X POST {base}/v1/agents/schedule-agent/messages \
  -H "Content-Type: application/json" -H "X-API-Key: KEY" \
  -d '{"user":"alice@corp.com","subject":"Meeting request","body":"Can we meet next week?"}'
```

---

## 6. Behavior guarantees (safe to rely on)

- **Isolation:** `user` A never sees `user` B's training, memory, or data.
- **Memory:** a user's training and per-subject context persist and are reused on later calls
  (survives restarts; it's stored server-side).
- **Idempotency of training:** re-sending the same `Private` text just adds guidance; use `DELETE`
  to reset.
- **No dangerous actions:** the agent only produces text replies — it never sends mail on your
  users' behalf, touches calendars, or calls other systems. Your platform decides what to do with
  the returned `reply`.

## 7. Pre-go-live checklist for the integrator

- [ ] Confirm `GET {base}/health` returns `ok` from your environment.
- [ ] Store the API key in backend config; confirm `401` without it and `200` with it.
- [ ] Decide and freeze the `user` key mapping (email recommended).
- [ ] Wire the two actions (work + Private training) and render `reply`.
- [ ] Handle timeouts (~60s), `5xx` retries with backoff, and `4xx` as user-visible errors.
- [ ] (Optional) Build the "what my assistant knows" + "reset" screens using GET/DELETE.

---

## 8. What to hand over (summary for the operator)

Give the platform owner: **(1)** this `INTEGRATION.md`, **(2)** `openapi.json` (or the live
`{base}/openapi.json` + `{base}/docs`), **(3)** the **base URL**, **(4)** the **API key**, and
**(5)** the list of agent IDs. That is everything needed to integrate — no source code required.
