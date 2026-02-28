"""Tests for the webhook endpoint."""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from httpx import AsyncClient, ASGITransport

from src.main import app


SAMPLE_EVENT = {
    "event_type": "pr_opened",
    "change_id": 5,
    "job_id": 42,
    "timestamp": "2026-02-28T10:30:00Z",
    "target_repo": "https://github.com/MadhuvanthiSriPad/billing-service",
    "target_service": "billing-service",
    "pr_url": "https://github.com/MadhuvanthiSriPad/billing-service/pull/99",
    "devin_session_url": "https://app.devin.ai/sessions/sess_abc123",
    "severity": "high",
    "is_breaking": True,
    "summary": "Added required sla_tier field",
    "changed_routes": ["POST /sessions"],
}


async def test_pr_opened_creates_jira_and_slack():
    """Happy path: Jira + Slack both succeed."""
    mock_jira = AsyncMock()
    mock_jira.create_issue.return_value = {"key": "ACCR-42", "self": "..."}
    mock_jira.browse_url = Mock(return_value="https://yourco.atlassian.net/browse/ACCR-42")
    mock_jira.close = AsyncMock()

    mock_slack = AsyncMock()
    mock_slack.send_message.return_value = {"ok": True}
    mock_slack.close = AsyncMock()

    with (
        patch("src.handlers.event_handler.JiraClient", return_value=mock_jira),
        patch("src.handlers.event_handler.SlackClient", return_value=mock_slack),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/webhooks/pr-opened", json=SAMPLE_EVENT)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processed"
    assert data["jira_issue_key"] == "ACCR-42"
    assert data["slack_sent"] is True
    assert data["errors"] == []


async def test_duplicate_webhook_is_idempotent():
    """Same job_id sent twice returns already_processed."""
    mock_jira = AsyncMock()
    mock_jira.create_issue.return_value = {"key": "ACCR-42"}
    mock_jira.browse_url = Mock(return_value="https://yourco.atlassian.net/browse/ACCR-42")
    mock_jira.close = AsyncMock()

    mock_slack = AsyncMock()
    mock_slack.send_message.return_value = {"ok": True}
    mock_slack.close = AsyncMock()

    with (
        patch("src.handlers.event_handler.JiraClient", return_value=mock_jira),
        patch("src.handlers.event_handler.SlackClient", return_value=mock_slack),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp1 = await client.post("/api/v1/webhooks/pr-opened", json=SAMPLE_EVENT)
            resp2 = await client.post("/api/v1/webhooks/pr-opened", json=SAMPLE_EVENT)

    assert resp1.status_code == 200
    assert resp1.json()["status"] == "processed"
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "already_processed"

    # Jira should only be called once.
    assert mock_jira.create_issue.call_count == 1


async def test_jira_failure_does_not_block_slack():
    """Jira fails, Slack still sends — partial status."""
    mock_jira = AsyncMock()
    mock_jira.create_issue.side_effect = RuntimeError("Jira unreachable")
    mock_jira.close = AsyncMock()

    mock_slack = AsyncMock()
    mock_slack.send_message.return_value = {"ok": True}
    mock_slack.close = AsyncMock()

    with (
        patch("src.handlers.event_handler.JiraClient", return_value=mock_jira),
        patch("src.handlers.event_handler.SlackClient", return_value=mock_slack),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/v1/webhooks/pr-opened", json=SAMPLE_EVENT)

    data = resp.json()
    assert data["status"] == "partial"
    assert data["slack_sent"] is True
    assert data["jira_issue_key"] is None
    assert len(data["errors"]) == 1


async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
