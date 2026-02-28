"""Tests for the event handler orchestration logic."""

from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import select

from src.database import async_session
from src.handlers.event_handler import handle_pr_opened
from src.models.jira_ticket import JiraTicket
from src.schemas.events import PROpenedEvent


def _sample_event(**overrides) -> PROpenedEvent:
    defaults = {
        "event_type": "pr_opened",
        "change_id": 1,
        "job_id": 10,
        "timestamp": "2026-02-28T10:30:00Z",
        "target_repo": "https://github.com/MadhuvanthiSriPad/billing-service",
        "target_service": "billing-service",
        "pr_url": "https://github.com/MadhuvanthiSriPad/billing-service/pull/1",
        "devin_session_url": "https://app.devin.ai/sessions/sess_1",
        "severity": "high",
        "is_breaking": True,
        "summary": "test change",
        "changed_routes": ["POST /sessions"],
    }
    defaults.update(overrides)
    return PROpenedEvent(**defaults)


async def test_both_services_fail_returns_failed():
    """Both Jira and Slack fail — status is 'failed'."""
    mock_jira = AsyncMock()
    mock_jira.create_issue.side_effect = RuntimeError("jira down")
    mock_jira.close = AsyncMock()

    mock_slack = AsyncMock()
    mock_slack.send_message.side_effect = RuntimeError("slack down")
    mock_slack.close = AsyncMock()

    with (
        patch("src.handlers.event_handler.JiraClient", return_value=mock_jira),
        patch("src.handlers.event_handler.SlackClient", return_value=mock_slack),
    ):
        async with async_session() as db:
            result = await handle_pr_opened(db, _sample_event())

    assert result.status == "failed"
    assert len(result.errors) == 2


async def test_jira_ticket_persisted():
    """On success, JiraTicket row is created."""
    mock_jira = AsyncMock()
    mock_jira.create_issue.return_value = {"key": "ACCR-1"}
    mock_jira.browse_url = Mock(return_value="https://x.atlassian.net/browse/ACCR-1")
    mock_jira.close = AsyncMock()

    mock_slack = AsyncMock()
    mock_slack.send_message.return_value = {"ok": True}
    mock_slack.close = AsyncMock()

    with (
        patch("src.handlers.event_handler.JiraClient", return_value=mock_jira),
        patch("src.handlers.event_handler.SlackClient", return_value=mock_slack),
    ):
        async with async_session() as db:
            await handle_pr_opened(db, _sample_event())

    async with async_session() as db:
        result = await db.execute(select(JiraTicket))
        ticket = result.scalar_one()
        assert ticket.jira_issue_key == "ACCR-1"
        assert ticket.job_id == 10
