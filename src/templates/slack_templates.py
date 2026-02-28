"""Slack Block Kit message builders."""

from __future__ import annotations

from src.schemas.events import PROpenedEvent


def build_pr_notification(
    event: PROpenedEvent,
    jira_issue_key: str | None = None,
    jira_issue_url: str | None = None,
) -> list[dict]:
    """Build Block Kit blocks for a PR-opened Slack notification."""
    severity_emoji = ":red_circle:" if event.is_breaking else ":large_yellow_circle:"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Remediation PR Ready for Review",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Service:*\n{event.target_service}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Severity:*\n{severity_emoji} {'BREAKING' if event.is_breaking else event.severity.upper()}",
                },
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Change summary:*\n{event.summary or 'Contract change detected'}",
            },
        },
    ]

    # Links section
    links_parts = [f":github: <{event.pr_url}|Pull Request>"]
    if jira_issue_key and jira_issue_url:
        links_parts.append(f":jira2: <{jira_issue_url}|{jira_issue_key}>")
    links_parts.append(f":robot_face: <{event.devin_session_url}|Devin Session>")

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": " | ".join(links_parts),
        },
    })

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": ":point_right: *Please review and merge this PR.*",
        },
    })

    blocks.append({"type": "divider"})

    return blocks
