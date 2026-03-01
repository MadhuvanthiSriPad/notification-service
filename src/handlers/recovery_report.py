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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.billing import ApiCoreClient, BillingClient
from src.clients.jira_client import JiraClient
from src.clients.slack_client import SlackClient
from src.config import settings
from src.models.jira_ticket import JiraTicket
from src.models.notification_event import NotificationEvent
from src.schemas.events import RecoveryCompleteEvent, WebhookResponse
from src.templates.jira_templates import build_recovery_comment
from src.templates.slack_templates import build_recovery_report, build_recovery_report_text

logger = logging.getLogger(__name__)


async def _create_tracking_session(event: RecoveryCompleteEvent) -> dict | None:
    """Best-effort: create a tracking session on api-core for this recovery.

    Includes the required ``data_residency`` field per the upstream
    contract change.
    """
    if not settings.api_core_url:
        return None
    try:
        client = ApiCoreClient()
        result = await client.create_session(
            team_id="notification-service",
            agent_name="recovery-handler",
            priority="high",
            data_residency=settings.default_data_residency,
            prompt=f"recovery_complete for change_id={event.change_id}",
            tags=f"change_id:{event.change_id}",
        )
        await client.close()
        return result
    except Exception as exc:
        logger.warning("Could not create tracking session on api-core: %s", exc)
        with suppress(Exception):
            await client.close()  # type: ignore[possibly-undefined]
        return None


async def _fetch_billing_summary() -> dict | None:
    """Best-effort fetch of the billing summary from billing-service."""
    if not settings.billing_url:
        return None
    try:
        client = BillingClient()
        result = await client.get_billing_summary()
        await client.close()
        return result
    except Exception as exc:
        logger.warning("Could not fetch billing summary: %s", exc)
        with suppress(Exception):
            await client.close()  # type: ignore[possibly-undefined]
        return None


async def handle_recovery_complete(
    db: AsyncSession,
    event: RecoveryCompleteEvent,
) -> WebhookResponse:
    """Process a recovery_complete webhook event."""
    idem_key = f"recovery_complete:{event.change_id}"

    existing = await db.execute(
        select(NotificationEvent).where(NotificationEvent.idempotency_key == idem_key)
    )
    if existing.scalar_one_or_none() is not None:
        logger.info("Duplicate recovery webhook for change %d — skipping", event.change_id)
        return WebhookResponse(status="already_processed")

    record = NotificationEvent(
        idempotency_key=idem_key,
        event_type=event.event_type,
        change_id=event.change_id,
        job_id=0,
        payload_json=json.dumps(event.model_dump(), default=str),
    )
    db.add(record)
    await db.flush()

    errors: list[str] = []

    # Create a tracking session on api-core (includes data_residency)
    tracking_session = await _create_tracking_session(event)
    if tracking_session:
        logger.info(
            "Tracking session for change %d: %s",
            event.change_id,
            tracking_session.get("session_id", "?"),
        )

    billing_summary = await _fetch_billing_summary()

    try:
        slack = SlackClient()
        blocks = build_recovery_report(event, billing_summary)
        fallback_text = build_recovery_report_text(event, billing_summary)
        await slack.send_message(blocks, text=fallback_text)
        record.slack_sent = True
        await slack.close()
    except Exception as exc:
        logger.error("Slack recovery report failed for change %d: %s", event.change_id, exc)
        record.slack_error = str(exc)[:500]
        errors.append(f"slack: {exc}")
        with suppress(Exception):
            await slack.close()  # type: ignore[possibly-undefined]

    jira_issue_key: str | None = None
    try:
        ticket_result = await db.execute(
            select(JiraTicket).where(JiraTicket.change_id == event.change_id)
        )
        tickets = ticket_result.scalars().all()

        if tickets:
            jira = JiraClient()
            comment_body = build_recovery_comment(event, billing_summary)
            jira_successes = 0
            for ticket in tickets:
                try:
                    await jira.add_comment(ticket.jira_issue_key, comment_body)
                    jira_issue_key = ticket.jira_issue_key
                    jira_successes += 1
                except Exception as exc:
                    logger.error(
                        "Failed to comment on %s: %s", ticket.jira_issue_key, exc
                    )
                    errors.append(f"jira_comment:{ticket.jira_issue_key}: {exc}")
            record.jira_sent = jira_successes > 0
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
