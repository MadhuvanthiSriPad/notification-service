"""Jira issue field builders using Atlassian Document Format (ADF)."""

from __future__ import annotations

from src.config import settings
from src.schemas.events import PROpenedEvent, RecoveryCompleteEvent


def _text_node(text: str) -> dict:
    return {"type": "text", "text": text}


def _bold_text(text: str) -> dict:
    return {"type": "text", "text": text, "marks": [{"type": "strong"}]}


def _link_node(text: str, href: str) -> dict:
    return {
        "type": "text",
        "text": text,
        "marks": [{"type": "link", "attrs": {"href": href}}],
    }


def _paragraph(*inline: dict) -> dict:
    return {"type": "paragraph", "content": list(inline)}


def _heading(text: str, level: int = 3) -> dict:
    return {
        "type": "heading",
        "attrs": {"level": level},
        "content": [_text_node(text)],
    }


def build_issue_fields(event: PROpenedEvent) -> dict:
    """Build Jira create-issue fields dict for a PR-opened event."""
    severity_label = "BREAKING" if event.is_breaking else event.severity.upper()
    summary = f"[ACCR] Downstream remediation PR for {event.target_service} — review required"

    routes_text = ", ".join(event.changed_routes) if event.changed_routes else "N/A"

    description_doc = {
        "version": 1,
        "type": "doc",
        "content": [
            _heading("Upstream Contract Change Details"),
            _paragraph(
                _bold_text("Severity: "),
                _text_node(f"{severity_label} ({event.severity})"),
            ),
            _paragraph(
                _bold_text("Summary: "),
                _text_node(event.summary or "Upstream contract change detected"),
            ),
            _paragraph(
                _bold_text("Changed routes: "),
                _text_node(routes_text),
            ),
            _heading("Downstream Remediation"),
            _paragraph(
                _bold_text("Downstream service: "),
                _text_node(event.target_service),
            ),
            _paragraph(
                _bold_text("Downstream repo: "),
                _text_node(event.target_repo),
            ),
            _paragraph(
                _bold_text("Downstream PR: "),
                _link_node(event.pr_url, event.pr_url),
            ),
            _paragraph(
                _bold_text("Devin session: "),
                _link_node(event.devin_session_url, event.devin_session_url),
            ),
            _heading("Action Required"),
            _paragraph(
                _text_node("Review and merge the downstream pull request linked above. "
                           "This PR was raised against the downstream team's repo by Devin "
                           "as part of automated contract change remediation."),
            ),
        ],
    }

    fields: dict = {
        "project": {"key": settings.jira_project_key},
        "summary": summary,
        "description": description_doc,
        "issuetype": {"name": "Task"},
        "labels": ["contract-change", "devin-remediation"],
    }
    if settings.jira_assignee_account_id:
        fields["assignee"] = {"accountId": settings.jira_assignee_account_id}

    return fields


def _bullet_list(*items: str) -> dict:
    return {
        "type": "bulletList",
        "content": [
            {"type": "listItem", "content": [_paragraph(_text_node(item))]}
            for item in items
        ],
    }


def build_recovery_comment(
    event: RecoveryCompleteEvent,
    billing_summary: dict | None = None,
) -> dict:
    """Build an ADF comment body for the post-incident recovery report."""
    mttr_min = event.mttr_seconds // 60
    mttr_str = f"{mttr_min}m" if mttr_min < 60 else f"{mttr_min // 60}h {mttr_min % 60}m"
    severity_label = "BREAKING" if event.is_breaking else event.severity.upper()
    routes_text = ", ".join(event.changed_routes) if event.changed_routes else "N/A"

    content = [
        _heading("Post-Incident Recovery Report", level=2),
        _paragraph(
            _bold_text("Status: "),
            _text_node("RESOLVED — all services remediated"),
        ),
        _paragraph(
            _bold_text("Severity: "),
            _text_node(f"{severity_label} ({event.severity})"),
        ),
        _paragraph(
            _bold_text("MTTR: "),
            _text_node(mttr_str),
        ),
        _paragraph(
            _bold_text("Summary: "),
            _text_node(event.summary or "Automated contract change recovery completed"),
        ),
        _paragraph(
            _bold_text("Changed routes: "),
            _text_node(routes_text),
        ),
        _heading("Services Remediated", level=3),
        _bullet_list(*[
            f"{j.target_service} — {j.pr_url or 'no PR'}"
            for j in event.jobs
        ]) if event.jobs else _paragraph(_text_node("No jobs recorded")),
    ]

    if billing_summary:
        total_revenue = billing_summary.get("total_revenue", 0)
        top_teams = billing_summary.get("top_teams", [])
        content.append(_heading("Platform Cost Context", level=3))
        content.append(_paragraph(
            _bold_text("Total platform spend: "),
            _text_node(f"${total_revenue:,.2f}"),
        ))
        if top_teams:
            content.append(_bullet_list(*[
                f"{t.get('team_name', t.get('team_id', '?'))}: "
                f"${t.get('total_cost', 0):,.2f} ({t.get('total_sessions', 0)} sessions)"
                for t in top_teams[:3]
            ]))

    return {"version": 1, "type": "doc", "content": content}
