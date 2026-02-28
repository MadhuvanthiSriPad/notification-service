"""Slack Block Kit message builders."""

from __future__ import annotations

from src.schemas.events import PROpenedEvent, RecoveryCompleteEvent


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


def build_recovery_report(
    event: RecoveryCompleteEvent,
    billing_summary: dict | None = None,
) -> list[dict]:
    """Build Block Kit blocks for the post-incident recovery report."""
    mttr_min = event.mttr_seconds // 60
    mttr_str = f"{mttr_min}m" if mttr_min < 60 else f"{mttr_min // 60}h {mttr_min % 60}m"
    severity_emoji = ":red_circle:" if event.is_breaking else ":large_yellow_circle:"
    svc_list = ", ".join(event.affected_services) if event.affected_services else "unknown"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":white_check_mark: Incident Resolved — Contract Recovery Complete",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Severity:*\n{severity_emoji} {'BREAKING' if event.is_breaking else event.severity.upper()}"},
                {"type": "mrkdwn", "text": f"*MTTR:*\n:stopwatch: {mttr_str}"},
                {"type": "mrkdwn", "text": f"*Services fixed:*\n{event.total_jobs}"},
                {"type": "mrkdwn", "text": f"*Blast radius:*\n{svc_list}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*What changed:*\n{event.summary or 'Contract change detected and remediated automatically.'}",
            },
        },
    ]

    # PRs merged
    if event.jobs:
        pr_lines = "\n".join(
            f"• `{j.target_service}` — <{j.pr_url}|PR merged>" if j.pr_url else f"• `{j.target_service}` — resolved"
            for j in event.jobs
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Services remediated:*\n{pr_lines}"},
        })

    # Billing context
    if billing_summary:
        total_revenue = billing_summary.get("total_revenue", 0)
        top_teams = billing_summary.get("top_teams", [])
        cost_lines = [f":moneybag: Platform total spend: *${total_revenue:,.2f}*"]
        for t in top_teams[:3]:
            cost_lines.append(
                f"  • {t.get('team_name', '?')}: ${t.get('total_cost', 0):,.2f} "
                f"({t.get('total_sessions', 0)} sessions)"
            )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(cost_lines)},
        })

    blocks.append({"type": "divider"})
    return blocks
