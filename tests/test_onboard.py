"""Tests for POST /v1/onboard — the single endpoint the meeting-manager button calls."""

import os
import tempfile

from fastapi.testclient import TestClient

from safi.api import create_app
from safi.config import Settings
from safi.llm import FakeLlmClient
from safi.models import AgentConfig
from safi.transport import InMemoryTransport


def _settings():
    d = tempfile.mkdtemp()
    agents = [
        AgentConfig(agent_id="reply-agent", name="Reply Agent",
                    mailbox="safi.replyagent@example.com", model="fake",
                    smtp={"host": "smtp.example.com", "port": 587, "user": "x", "password": "y"}),
        AgentConfig(agent_id="schedule-agent", name="Schedule Agent",
                    mailbox="safi.scheduleagent@example.com", model="fake",
                    smtp={"host": "smtp.example.com", "port": 587, "user": "x", "password": "y"}),
    ]
    return Settings(
        db_path=os.path.join(d, "t.sqlite"), files_dir=os.path.join(d, "files"),
        llm_mode="fake", default_model="fake", reject_policy="reply",
        poll_interval=60, agents=agents, multi_tenant=True,
    )


def _client(transport, api_key=None):
    app = create_app(_settings(), llm=FakeLlmClient(), transport=transport, api_key=api_key)
    return TestClient(app)


def test_onboard_sends_instructions_email_and_returns_status():
    transport = InMemoryTransport()
    client = _client(transport)
    resp = client.post("/v1/onboard", json={"email": "alice@corp.com", "name": "Alice"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "sent"
    assert data["email"] == "alice@corp.com"
    assert "email" in data["message"].lower()

    # exactly one instructions email went to the user
    sent = transport.sent_to("alice@corp.com")
    assert len(sent) == 1
    msg = sent[0]
    assert msg["from"] == "safi.replyagent@example.com"      # onboarding sender
    assert "Safi" in msg["subject"]
    # body explains how to use the assistants
    assert "safi.replyagent@example.com" in msg["body"]
    assert "safi.scheduleagent@example.com" in msg["body"]
    assert "Private" in msg["body"]
    assert "Alice" in msg["body"]


def test_onboard_rejects_bad_email():
    client = _client(InMemoryTransport())
    resp = client.post("/v1/onboard", json={"email": "not-an-email"})
    assert resp.status_code == 400


def test_onboard_reports_send_failure_as_502():
    class FailingTransport(InMemoryTransport):
        def send(self, *a, **k):
            raise RuntimeError("smtp down")

    client = _client(FailingTransport())
    resp = client.post("/v1/onboard", json={"email": "alice@corp.com"})
    assert resp.status_code == 502
    assert "error" in resp.json()


def test_onboard_requires_api_key_when_set():
    transport = InMemoryTransport()
    client = _client(transport, api_key="secret")
    # missing key
    assert client.post("/v1/onboard", json={"email": "a@b.com"}).status_code == 401
    # correct key
    ok = client.post("/v1/onboard", json={"email": "a@b.com"},
                     headers={"X-API-Key": "secret"})
    assert ok.status_code == 200
