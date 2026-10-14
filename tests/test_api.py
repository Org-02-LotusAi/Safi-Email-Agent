"""Tests for the HTTP API (safi/api.py). Uses fastapi.testclient.TestClient so no
real network/uvicorn process is needed. The LLM is a FakeLlmClient injected at app
creation, so no ANTHROPIC_API_KEY is required.
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from safi.api import create_app
from safi.config import Settings
from safi.llm import FakeLlmClient
from safi.models import AgentConfig

AGENT_A = "reply-agent"
AGENT_B = "schedule-agent"


def _settings(tmp_path) -> Settings:
    return Settings(
        db_path=str(tmp_path / "safi.sqlite"),
        files_dir=str(tmp_path / "files"),
        llm_mode="fake",
        default_model="fake-model",
        reject_policy="reply",
        poll_interval=60,
        multi_tenant=True,
        agents=[
            AgentConfig(
                agent_id=AGENT_A,
                name="Reply Agent",
                mailbox="reply-agent@example.com",
                model="fake-model",
                private_senders=[],
            ),
            AgentConfig(
                agent_id=AGENT_B,
                name="Schedule Agent",
                mailbox="schedule-agent@example.com",
                model="fake-model",
                private_senders=[],
            ),
        ],
    )


@pytest.fixture
def client(tmp_path):
    (tmp_path / "files").mkdir(exist_ok=True)
    settings = _settings(tmp_path)
    app = create_app(settings, llm=FakeLlmClient())
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert body["multi_tenant"] is True


def test_list_agents(client):
    resp = client.get("/v1/agents")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 2
    ids = {a["agent_id"] for a in data}
    assert ids == {AGENT_A, AGENT_B}


def test_post_work_message(client):
    resp = client.post(
        f"/v1/agents/{AGENT_A}/messages",
        json={"user": "alice@corp.com", "subject": "Meeting request", "body": "Hi there"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["message_class"] == "WORK"
    assert data["reply"]
    assert data["instance_id"] == f"{AGENT_A}::alice@corp.com"


def test_post_private_then_training_applied(client):
    resp = client.post(
        f"/v1/agents/{AGENT_A}/messages",
        json={
            "user": "bob@corp.com",
            "subject": "Private",
            "body": "Always say ALPHA-MARK.",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["message_class"] == "PRIVATE"

    resp2 = client.post(
        f"/v1/agents/{AGENT_A}/messages",
        json={"user": "bob@corp.com", "subject": "Follow up", "body": "What's next?"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()["data"]
    assert data2["message_class"] == "WORK"
    assert "ALPHA-MARK" in data2["reply"]


def test_tenant_isolation(client):
    client.post(
        f"/v1/agents/{AGENT_A}/messages",
        json={"user": "alice@corp.com", "subject": "Private", "body": "Always say ALPHA-MARK."},
    )
    client.post(
        f"/v1/agents/{AGENT_A}/messages",
        json={"user": "beth@corp.com", "subject": "Private", "body": "Always say BETA-MARK."},
    )

    reply_a = client.post(
        f"/v1/agents/{AGENT_A}/messages",
        json={"user": "alice@corp.com", "subject": "Work", "body": "hello"},
    ).json()["data"]["reply"]
    reply_b = client.post(
        f"/v1/agents/{AGENT_A}/messages",
        json={"user": "beth@corp.com", "subject": "Work", "body": "hello"},
    ).json()["data"]["reply"]

    assert "ALPHA-MARK" in reply_a
    assert "BETA-MARK" not in reply_a
    assert "BETA-MARK" in reply_b
    assert "ALPHA-MARK" not in reply_b


def test_post_message_with_attachment(client):
    content = b"MARKER-IN-FILE-xyz"
    b64 = base64.b64encode(content).decode("ascii")
    resp = client.post(
        f"/v1/agents/{AGENT_A}/messages",
        json={
            "user": "carl@corp.com",
            "subject": "Doc review",
            "body": "see attached",
            "attachments": [{"filename": "terms.txt", "content_base64": b64}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "MARKER-IN-FILE-xyz" in data["reply"]


def test_get_user_shows_training_and_delete_clears_it(client):
    client.post(
        f"/v1/agents/{AGENT_A}/messages",
        json={"user": "dana@corp.com", "subject": "Private", "body": "Always say ALPHA-MARK."},
    )

    resp = client.get(f"/v1/agents/{AGENT_A}/users/dana@corp.com")
    assert resp.status_code == 200
    training = resp.json()["data"]["training"]
    assert any("ALPHA-MARK" in t["content"] for t in training)

    del_resp = client.delete(f"/v1/agents/{AGENT_A}/users/dana@corp.com")
    assert del_resp.status_code == 200
    assert "deleted" in del_resp.json()["data"]

    resp2 = client.get(f"/v1/agents/{AGENT_A}/users/dana@corp.com")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["training"] == []


def test_unprovisioned_user_returns_empty(client):
    resp = client.get(f"/v1/agents/{AGENT_A}/users/nobody@corp.com")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["training"] == []
    assert data["subjects"] == []


def test_unknown_agent_404(client):
    resp = client.post(
        f"/v1/agents/unknown/messages",
        json={"user": "x@corp.com", "subject": "s", "body": "b"},
    )
    assert resp.status_code == 404
    assert "error" in resp.json()


def test_bad_base64_400(client):
    resp = client.post(
        f"/v1/agents/{AGENT_A}/messages",
        json={
            "user": "x@corp.com",
            "subject": "s",
            "body": "b",
            "attachments": [{"filename": "f.txt", "content_base64": "not-valid-base64!!"}],
        },
    )
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_auth_required_when_api_key_set(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(settings, llm=FakeLlmClient(), api_key="secret")
    client = TestClient(app)

    resp = client.get("/v1/agents")
    assert resp.status_code == 401

    resp2 = client.get("/v1/agents", headers={"X-API-Key": "secret"})
    assert resp2.status_code == 200

    # /health is always open, no auth needed
    resp3 = client.get("/health")
    assert resp3.status_code == 200
