"""Tests for the event handler orchestration logic."""

from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import select

from src.config import settings
from src.database import async_session
from src.handlers.event_handler import handle_pr_opened
from src.models.jira_ticket import JiraTicket
from src.schemas.events import PROpenedEvent


def _extract_adf_text(node: dict | list) -> str:
    if isinstance(node, list):
        return " ".join(_extract_adf_text(item) for item in node)
    if not isinstance(node, dict):
        return str(node)
    text = node.get("text", "")
    content = node.get("content", [])
    child_text = _extract_adf_text(content) if content else ""
    return " ".join(part for part in (text, child_text) if part)


def _sample_notification_bundle(**overrides) -> dict:
    payload = {
        "author": "devin",
        "assertions": {
            "source_repo": "https://github.com/MadhuvanthiSriPad/api-core",
            "target_repo": "https://github.com/MadhuvanthiSriPad/billing-service",
            "target_service": "billing-service",
            "pr_url": "https://github.com/MadhuvanthiSriPad/billing-service/pull/1",
        },
        "jira": {
            "summary": "Devin-authored Jira summary",
            "description_text": "Devin-authored Jira description\n\n- check billing gateway\n- verify invoice tests",
        },
        "slack": {
            "text": "Devin-authored Slack text",
            "blocks": [],
        },
    }
    payload.update(overrides)
    return payload


def _sample_event(**overrides) -> PROpenedEvent:
    defaults = {
        "event_type": "pr_opened",
        "change_id": 1,
        "job_id": 10,
        "timestamp": "2026-02-28T10:30:00Z",
        "source_repo": "https://github.com/MadhuvanthiSriPad/api-core",
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
            result = await handle_pr_opened(db, _sample_event(notification_bundle=_sample_notification_bundle()))

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
            await handle_pr_opened(db, _sample_event(notification_bundle=_sample_notification_bundle()))

    async with async_session() as db:
        result = await db.execute(select(JiraTicket))
        ticket = result.scalar_one()
        assert ticket.jira_issue_key == "ACCR-1"
        assert ticket.job_id == 10


async def test_valid_notification_bundle_is_used_for_jira_and_slack():
    mock_jira = AsyncMock()
    mock_jira.create_issue.return_value = {"key": "ACCR-77"}
    mock_jira.browse_url = Mock(return_value="https://x.atlassian.net/browse/ACCR-77")
    mock_jira.close = AsyncMock()

    mock_slack = AsyncMock()
    mock_slack.send_message.return_value = {"ok": True}
    mock_slack.close = AsyncMock()

    event = _sample_event(notification_bundle=_sample_notification_bundle())

    with (
        patch("src.handlers.event_handler.JiraClient", return_value=mock_jira),
        patch("src.handlers.event_handler.SlackClient", return_value=mock_slack),
    ):
        async with async_session() as db:
            await handle_pr_opened(db, event)

    jira_fields = mock_jira.create_issue.await_args.args[0]
    slack_blocks = mock_slack.send_message.await_args.args[0]
    slack_text = mock_slack.send_message.await_args.kwargs["text"]

    assert jira_fields["summary"] == "Devin-authored Jira summary"
    assert "Devin-authored Jira description" in _extract_adf_text(jira_fields["description"])
    assert "Canonical Context" in _extract_adf_text(jira_fields["description"])
    assert slack_text == "Devin-authored Slack text"
    assert slack_blocks[0]["type"] == "header"


async def test_billing_service_uses_repo_specific_jira_project(monkeypatch):
    mock_jira = AsyncMock()
    mock_jira.create_issue.return_value = {"key": "BS-77"}
    mock_jira.browse_url = Mock(return_value="https://x.atlassian.net/browse/BS-77")
    mock_jira.close = AsyncMock()

    mock_slack = AsyncMock()
    mock_slack.send_message.return_value = {"ok": True}
    mock_slack.close = AsyncMock()

    monkeypatch.setattr(settings, "jira_project_key", "AC")
    monkeypatch.setattr(
        settings,
        "jira_project_keys_by_repo",
        {
            "api-core": "AC",
            "billing-service": "BS",
            "notification-service": "NOT",
            "dashboard-service": "DS",
        },
    )

    event = _sample_event(notification_bundle=_sample_notification_bundle())

    with (
        patch("src.handlers.event_handler.JiraClient", return_value=mock_jira),
        patch("src.handlers.event_handler.SlackClient", return_value=mock_slack),
    ):
        async with async_session() as db:
            await handle_pr_opened(db, event)

    jira_fields = mock_jira.create_issue.await_args.args[0]

    assert jira_fields["project"] == {"key": "BS"}


async def test_invalid_notification_bundle_skips_jira_and_keeps_slack_fallback():
    mock_jira = AsyncMock()
    mock_jira.close = AsyncMock()

    mock_slack = AsyncMock()
    mock_slack.send_message.return_value = {"ok": True}
    mock_slack.close = AsyncMock()

    event = _sample_event(notification_bundle={
        "author": "devin",
        "assertions": {
            "source_repo": "https://github.com/MadhuvanthiSriPad/api-core",
            "target_repo": "https://github.com/MadhuvanthiSriPad/dashboard-service",
            "target_service": "billing-service",
            "pr_url": "https://github.com/MadhuvanthiSriPad/billing-service/pull/1",
        },
        "jira": {
            "summary": "Wrong summary that should be ignored",
            "description_text": "Wrong Jira description",
        },
        "slack": {
            "text": "Wrong Slack text",
            "blocks": [],
        },
    })

    with (
        patch("src.handlers.event_handler.JiraClient", return_value=mock_jira),
        patch("src.handlers.event_handler.SlackClient", return_value=mock_slack),
    ):
        async with async_session() as db:
            result = await handle_pr_opened(db, event)

    slack_text = mock_slack.send_message.await_args.kwargs["text"]

    assert result.status == "partial"
    assert result.jira_issue_key is None
    assert result.errors == ["jira: invalid Devin-authored notification bundle"]
    assert mock_jira.create_issue.await_count == 0
    assert slack_text != "Wrong Slack text"
