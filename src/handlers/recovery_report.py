"""Orchestrates post-incident recovery reporting.

When all remediation PRs for a contract change are merged, api-core fires a
recovery_complete webhook.  This handler:

1. Checks idempotency — skip if already processed.
2. Optionally fetches a billing summary from billing-service.
3. Sends a rich Slack post-incident report.
4. Adds a resolution comment to every open Jira ticket for the change.
5. Persists results.

Graceful degradation: billing, Slack, or Jira failures do not block each other.
"""

from __future__ import annotations

import json
import logging
from contextlib import suppress

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.jira_client import JiraClient
from src.clients.slack_client import SlackClient
from src.config import settings
from src.models.jira_ticket import JiraTicket
from src.models.notification_event import NotificationEvent
from src.schemas.events import RecoveryCompleteEvent, WebhookResponse
from src.templates.jira_templates import build_recovery_comment
from src.templates.slack_templates import build_recovery_report

logger = logging.getLogger(__name__)


async def _fetch_billing_summary() -> dict | None:
    """Best-effort fetch of the billing summary from billing-service."""
    if not settings.billing_url:
        return None
    url = f"{settings.billing_url.rstrip('/')}/api/v1/billing/summary"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("Could not fetch billing summary: %s", exc)
        return None


async def handle_recovery_complete(
    db: AsyncSession,
    event: RecoveryCompleteEvent,
) -> WebhookResponse:
    """Process a recovery_complete webhook event."""
    idem_key = f"recovery_complete:{event.change_id}"

    # ── Idempotency check ──
    existing = await db.execute(
        select(NotificationEvent).where(NotificationEvent.idempotency_key == idem_key)
    )
    if existing.scalar_one_or_none() is not None:
        logger.info("Duplicate recovery webhook for change %d — skipping", event.change_id)
        return WebhookResponse(status="already_processed")

    # Create tracking record immediately so a racing duplicate gets rejected.
    record = NotificationEvent(
        idempotency_key=idem_key,
        event_type=event.event_type,
        change_id=event.change_id,
        job_id=0,  # recovery events are per-change, not per-job
        payload_json=json.dumps(event.model_dump(), default=str),
    )
    db.add(record)
    await db.flush()

    errors: list[str] = []

    # ── Step 1: Fetch billing context (best-effort) ──
    billing_summary = await _fetch_billing_summary()

    # ── Step 2: Slack post-incident report ──
    try:
        slack = SlackClient()
        blocks = build_recovery_report(event, billing_summary)
        await slack.send_message(blocks, text="Incident Resolved — Contract Recovery Complete")
        record.slack_sent = True
        await slack.close()
    except Exception as exc:
        logger.error("Slack recovery report failed for change %d: %s", event.change_id, exc)
        record.slack_error = str(exc)[:500]
        errors.append(f"slack: {exc}")
        with suppress(Exception):
            await slack.close()  # type: ignore[possibly-undefined]

    # ── Step 3: Add resolution comment to open Jira tickets ──
    jira_issue_key: str | None = None
    try:
        # Find all Jira tickets created for jobs under this change_id
        ticket_result = await db.execute(
            select(JiraTicket).where(JiraTicket.change_id == event.change_id)
        )
        tickets = ticket_result.scalars().all()

        if tickets:
            jira = JiraClient()
            comment_body = build_recovery_comment(event, billing_summary)
            for ticket in tickets:
                try:
                    await jira.add_comment(ticket.jira_issue_key, comment_body)
                    jira_issue_key = ticket.jira_issue_key  # keep last for response
                except Exception as exc:
                    logger.error(
                        "Failed to comment on %s: %s", ticket.jira_issue_key, exc
                    )
                    errors.append(f"jira_comment:{ticket.jira_issue_key}: {exc}")
            record.jira_sent = True
            await jira.close()
        else:
            logger.info("No Jira tickets found for change %d", event.change_id)
    except Exception as exc:
        logger.error("Jira commenting failed for change %d: %s", event.change_id, exc)
        record.jira_error = str(exc)[:500]
        errors.append(f"jira: {exc}")
        with suppress(Exception):
            await jira.close()  # type: ignore[possibly-undefined]

    await db.commit()

    status = "processed"
    if errors:
        status = "partial" if (record.jira_sent or record.slack_sent) else "failed"

    return WebhookResponse(
        status=status,
        jira_issue_key=jira_issue_key,
        slack_sent=record.slack_sent,
        errors=errors,
    )
