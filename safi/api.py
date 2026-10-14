"""HTTP API (FastAPI) so an external platform can call SAFI directly (operator
extension; not in SOW doc §43). Wraps :func:`safi.service.process_direct` — each
inbound ``user`` is routed to their own isolated per-user agent instance exactly as
the email pipeline does (see :mod:`safi.tenancy`).

SQLite connections cannot cross threads, and FastAPI runs sync endpoints in a
threadpool, so this module never shares one :class:`safi.db.Store` across requests:
a fresh ``Store`` is opened per request via a dependency and closed in a
``finally``.
"""

from __future__ import annotations

import base64
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import safi
from .config import Settings, apply_seed, build_llm
from .db import Store, init_db
from .logging_setup import get_logger
from .models import AgentConfig
from .onboarding import build_onboarding_email
from .service import process_direct
from .transport import ImapSmtpTransport
from . import tenancy


# --- request/response models ------------------------------------------------
class AttachmentIn(BaseModel):
    filename: str
    content_base64: str


class MessageIn(BaseModel):
    user: str = Field(..., description="Tenant identity; isolates per-user instances")
    subject: str
    body: str
    attachments: list[AttachmentIn] | None = None


class AgentOut(BaseModel):
    agent_id: str
    name: str
    mailbox: str


class OnboardIn(BaseModel):
    email: str = Field(..., description="The user's email address to send instructions to")
    name: str | None = Field(default=None, description="Optional display name for the greeting")


# --- app factory --------------------------------------------------------------
def create_app(settings: Settings, llm=None, api_key: str | None = None,
               transport=None) -> FastAPI:
    init_db(settings.db_path)
    seed_store = Store(settings.db_path)
    try:
        apply_seed(seed_store, settings.agents)
    finally:
        seed_store.close()

    llm = llm if llm is not None else build_llm(settings)
    api_key = api_key if api_key is not None else os.environ.get("SAFI_API_KEY")
    transport = transport if transport is not None else ImapSmtpTransport()
    logger = get_logger("safi.api")
    multi_tenant = settings.multi_tenant

    agents_by_id: dict[str, AgentConfig] = {a.agent_id: a for a in settings.agents}

    app = FastAPI(title="SAFI API")
    app.state.settings = settings
    app.state.llm = llm
    app.state.api_key = api_key

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(_request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.status_code, "message": exc.detail}},
        )

    def get_store():
        store = Store(settings.db_path)
        try:
            yield store
        finally:
            store.close()

    def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
        if api_key and x_api_key != api_key:
            raise HTTPException(status_code=401, detail="invalid or missing API key")

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "version": safi.__version__,
            "multi_tenant": multi_tenant,
        }

    # The mailbox that sends onboarding instructions: prefer "reply-agent", else the first
    # enabled agent that has SMTP configured.
    def _onboarding_sender() -> AgentConfig | None:
        preferred = agents_by_id.get("reply-agent")
        if preferred and preferred.smtp:
            return preferred
        for a in settings.agents:
            if a.enabled and a.smtp:
                return a
        return None

    @app.post("/v1/onboard", dependencies=[Depends(require_api_key)])
    def onboard(payload: OnboardIn):
        """Email the user the instructions for using their Safi assistants.

        This is the single endpoint the meeting-manager button calls. On success it returns
        ``{"data": {"status": "sent", ...}}`` so the platform can show "Check your email for
        instructions."
        """
        email = (payload.email or "").strip()
        if "@" not in email:
            raise HTTPException(status_code=400, detail="a valid 'email' is required")

        sender = _onboarding_sender()
        if sender is None:
            raise HTTPException(
                status_code=503,
                detail="no agent mailbox with SMTP is configured to send instructions",
            )

        subject, body = build_onboarding_email(settings.agents, payload.name)
        try:
            transport.send(sender, to_addr=email, subject=subject, body=body)
        except Exception as exc:
            logger.error("onboarding send failed to %s: %s", email, exc)
            raise HTTPException(
                status_code=502,
                detail="failed to send the instructions email; please try again",
            )

        return {"data": {
            "status": "sent",
            "email": email,
            "message": "Instructions have been emailed. Please check your inbox.",
        }}

    @app.get("/v1/agents", dependencies=[Depends(require_api_key)])
    def list_agents():
        data = [
            {"agent_id": a.agent_id, "name": a.name, "mailbox": a.mailbox}
            for a in settings.agents
        ]
        return {"data": data}

    @app.post("/v1/agents/{agent_id}/messages", dependencies=[Depends(require_api_key)])
    def post_message(agent_id: str, payload: MessageIn, store: Store = Depends(get_store)):
        base_agent = agents_by_id.get(agent_id)
        if base_agent is None:
            raise HTTPException(status_code=404, detail=f"unknown agent_id {agent_id!r}")

        attachments: list[tuple[str, bytes]] | None = None
        if payload.attachments:
            attachments = []
            for att in payload.attachments:
                try:
                    data = base64.b64decode(att.content_base64, validate=True)
                except Exception:
                    raise HTTPException(
                        status_code=400,
                        detail=f"invalid base64 content for attachment {att.filename!r}",
                    )
                attachments.append((att.filename, data))

        record = process_direct(
            store, base_agent, llm,
            from_email=payload.user,
            subject=payload.subject,
            body=payload.body,
            attachments=attachments,
            files_dir=settings.files_dir,
            logger=logger,
            multi_tenant=multi_tenant,
        )

        instance_id = tenancy.instance_id(agent_id, payload.user) if multi_tenant else agent_id
        status = record.get("status", "error")
        message_class = (
            "PRIVATE" if status.startswith("private_") else "WORK"
        )
        reply = record.get("ack_text") if message_class == "PRIVATE" else record.get("reply_text")

        data = {
            "agent_id": agent_id,
            "instance_id": instance_id,
            "user": payload.user,
            "message_class": message_class,
            "reply": reply,
            "status": status,
            "micro_session_id": record.get("micro_session_id"),
            "training_added": record.get("training_added"),
        }
        return {"data": data}

    @app.get("/v1/agents/{agent_id}/users/{user}", dependencies=[Depends(require_api_key)])
    def get_user(agent_id: str, user: str, store: Store = Depends(get_store)):
        if agent_id not in agents_by_id:
            raise HTTPException(status_code=404, detail=f"unknown agent_id {agent_id!r}")

        iid = tenancy.instance_id(agent_id, user)
        training = [
            {
                "category": row["category"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            for row in store.get_training(iid)
        ]
        rows = store.conn.execute(
            "SELECT display_subject, summary, updated_at FROM subject_context WHERE agent_id=?",
            (iid,),
        ).fetchall()
        subjects = [
            {
                "canonical_subject": row["display_subject"],
                "summary": row["summary"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
        return {"data": {"instance_id": iid, "training": training, "subjects": subjects}}

    @app.delete("/v1/agents/{agent_id}/users/{user}", dependencies=[Depends(require_api_key)])
    def delete_user(agent_id: str, user: str, store: Store = Depends(get_store)):
        if agent_id not in agents_by_id:
            raise HTTPException(status_code=404, detail=f"unknown agent_id {agent_id!r}")

        iid = tenancy.instance_id(agent_id, user)
        deleted = store.purge_agent(iid)
        return {"data": {"deleted": deleted}}

    return app
