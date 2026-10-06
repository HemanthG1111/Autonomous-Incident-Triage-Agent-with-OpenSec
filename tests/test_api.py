"""test_api.py — Unit and integration tests for FastAPI endpoints."""

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import pytest

from app import api


@pytest.fixture
def client():
    return TestClient(api)


def test_healthz_endpoint(client):
    """GET /healthz returns 200 and {'status': 'ok'} without calling DB or LLM."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("app.service_chat")
def test_chat_endpoint_completed(mock_chat, client):
    """POST /chat returns COMPLETED when agent finishes without escalation."""
    mock_chat.return_value = {
        "status": "COMPLETED",
        "thread_id": "test-123",
        "response": "Investigated auth service. Healthy.",
    }
    response = client.post("/chat", json={"thread_id": "test-123", "message": "Check auth"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "COMPLETED"
    assert data["thread_id"] == "test-123"
    assert "Investigated" in data["response"]


@patch("app.service_chat")
def test_chat_endpoint_awaiting_approval(mock_chat, client):
    """POST /chat returns AWAITING_APPROVAL when sensitive tool is called."""
    mock_chat.return_value = {
        "status": "AWAITING_APPROVAL",
        "thread_id": "test-456",
        "pending_action": "escalate_ticket",
        "parameters": {"ticket_title": "Auth Down", "severity": "high"},
        "response": "Human approval required",
    }
    response = client.post("/chat", json={"thread_id": "test-456", "message": "Auth down, escalate!"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "AWAITING_APPROVAL"
    assert data["pending_action"] == "escalate_ticket"
    assert data["parameters"]["severity"] == "high"


@patch("app.service_approve")
def test_approve_endpoint_success(mock_approve, client):
    """POST /approve returns RESOLVED when pending action is approved."""
    mock_approve.return_value = {
        "status": "RESOLVED",
        "thread_id": "test-456",
        "response": "Ticket INC-1234 created.",
    }
    response = client.post("/approve", json={"thread_id": "test-456", "approved": True})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "RESOLVED"


@patch("app.service_approve")
def test_approve_endpoint_not_found(mock_approve, client):
    """POST /approve returns 400 when no escalation is pending."""
    mock_approve.return_value = None
    response = client.post("/approve", json={"thread_id": "non-existent", "approved": True})
    assert response.status_code == 400
    assert "No pending escalation" in response.json()["detail"]


@patch("app.service_reject")
def test_reject_endpoint_success(mock_reject, client):
    """POST /reject returns REJECTED_AND_RESUMED with rejection reason."""
    mock_reject.return_value = {
        "status": "REJECTED_AND_RESUMED",
        "thread_id": "test-456",
        "response": "Escalation rejected by engineer.",
    }
    response = client.post("/reject", json={"thread_id": "test-456", "reason": "Maintenance window"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "REJECTED_AND_RESUMED"


@patch("app.service_reject")
def test_reject_endpoint_not_found(mock_reject, client):
    """POST /reject returns 400 when no escalation is pending."""
    mock_reject.return_value = None
    response = client.post("/reject", json={"thread_id": "non-existent", "reason": "No reason"})
    assert response.status_code == 400
    assert "No pending escalation" in response.json()["detail"]
