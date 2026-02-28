"""Orchestrates Jira ticket creation and Slack notification.

Idempotent: duplicate webhooks for the same job_id are detected and skipped.
Graceful degradation: Jira failure does not block Slack, and vice versa.
"""

from __future__ import annotations

import json
import logging
from contextlib import suppress

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.jira_client import JiraClient
from src.clients.slack_client import SlackClient
from src.models.notification_event import NotificationEvent
from src.models.jira_ticket import JiraTicket
from src.schemas.events import PROpenedEvent, WebhookResponse
from src.templates.jira_templates import build_issue_fields
from src.templates.slack_templates import build_pr_notification

logger = logging.getLogger(__name__)


async def handle_pr_opened(
    db: AsyncSession,
    event: PROpenedEvent,
) -> WebhookResponse:
    """Process a pr_opened webhook event.

    1. Check idempotency — skip if already processed.
    2. Create Jira ticket.
    3. Send Slack message (includes Jira link if step 2 succeeded).
    4. Persist results.
    """
    idem_key = f"pr_opened:{event.job_id}"

    # ── Idempotency check ──
    existing = await db.execute(
        select(NotificationEvent).where(NotificationEvent.idempotency_key == idem_key)
    )
    if existing.scalar_one_or_none() is not None:
        logger.info("Duplicate webhook for job %d — skipping", event.job_id)
        return WebhookResponse(status="already_processed")

    # Create tracking record immediately so a racing duplicate gets rejected.
    record = NotificationEvent(
        idempotency_key=idem_key,
        event_type=event.event_type,
        change_id=event.change_id,
        job_id=event.job_id,
        payload_json=json.dumps(event.model_dump(), default=str),
    )
    db.add(record)
    await db.flush()

    errors: list[str] = []
    jira_issue_key: str | None = None
    jira_issue_url: str | None = None

    # ── Step 1: Jira ──
    try:
        jira = JiraClient()
        fields = build_issue_fields(event)
        result = await jira.create_issue(fields)
        jira_issue_key = result.get("key", "")
        jira_issue_url = jira.browse_url(jira_issue_key)

        ticket = JiraTicket(
            change_id=event.change_id,
            job_id=event.job_id,
            jira_issue_key=jira_issue_key,
            jira_issue_url=jira_issue_url,
        )
        db.add(ticket)
        record.jira_sent = True
        await jira.close()
    except Exception as exc:
        logger.error("Jira ticket creation failed for job %d: %s", event.job_id, exc)
        record.jira_error = str(exc)[:500]
        errors.append(f"jira: {exc}")
        with suppress(Exception):
            await jira.close()  # type: ignore[possibly-undefined]

    # ── Step 2: Slack ──
    try:
        slack = SlackClient()
        blocks = build_pr_notification(event, jira_issue_key, jira_issue_url)
        await slack.send_message(blocks)
        record.slack_sent = True
        await slack.close()
    except Exception as exc:
        logger.error("Slack notification failed for job %d: %s", event.job_id, exc)
        record.slack_error = str(exc)[:500]
        errors.append(f"slack: {exc}")
        with suppress(Exception):
            await slack.close()  # type: ignore[possibly-undefined]

    await db.commit()

    status = "processed"
    if errors:
        status = "partial" if (record.jira_sent or record.slack_sent) else "failed"

    return WebhookResponse(
        status=status,
        jira_issue_key=jira_issue_key,
        jira_issue_url=jira_issue_url,
        slack_sent=record.slack_sent,
        errors=errors,
    )
