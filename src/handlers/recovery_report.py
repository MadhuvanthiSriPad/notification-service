"""Orchestrates post-incident recovery reporting.

When all remediation jobs for a contract change are resolved, api-core
sends a ``recovery_complete`` webhook.  This handler:

1. Checks idempotency.
2. Fetches extended change details from api-core (including ``impact_sets``
   with the new ``method`` field).
3. Optionally enriches the report with billing data.
4. Adds a Jira comment to every open ticket for the change.
5. Sends a Slack post-incident report.
6. Persists the outcome.
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
from src.templates.slack_templates import build_recovery_report

logger = logging.getLogger(__name__)


def _format_impact_line(impact: dict) -> str:
    """Build a human-readable line for a single impact set entry.

    Handles the new ``method`` field (nullable string) added by the
    upstream api-core contract change.
    """
    method = impact.get("method") or "ANY"
    route = impact.get("route_template", "unknown")
    service = impact.get("caller_service", "unknown")
    calls = impact.get("calls_last_7d", 0)
    return f"{method} {route} ({service}, {calls} calls/7d)"


async def handle_recovery_complete(
    db: AsyncSession,
    event: RecoveryCompleteEvent,
) -> WebhookResponse:
    """Process a ``recovery_complete`` webhook event.

    1. Idempotency check.
    2. Fetch change detail from api-core (includes ``impact_sets`` with
       ``method``).
    3. Fetch billing summary (optional).
    4. Post Jira comment on every ticket for this ``change_id``.
    5. Send Slack recovery report.
    6. Persist results.
    """
    idem_key = f"recovery_complete:{event.change_id}"

    # -- Idempotency ----------------------------------------------------------
    existing = await db.execute(
        select(NotificationEvent).where(
            NotificationEvent.idempotency_key == idem_key
        )
    )
    if existing.scalar_one_or_none() is not None:
        logger.info(
            "Duplicate recovery webhook for change %d — skipping",
            event.change_id,
        )
        return WebhookResponse(status="already_processed")

    record = NotificationEvent(
        idempotency_key=idem_key,
        event_type=event.event_type,
        change_id=event.change_id,
        job_id=0,  # recovery events are change-level, not job-level
        payload_json=json.dumps(event.model_dump(), default=str),
    )
    db.add(record)
    await db.flush()

    errors: list[str] = []

    # -- Fetch change detail from api-core ------------------------------------
    change_detail: dict | None = None
    if settings.api_core_url:
        try:
            api_core = ApiCoreClient(settings.api_core_url)
            change_detail = await api_core.get_change_detail(event.change_id)
            await api_core.close()
        except Exception as exc:
            logger.warning("api-core fetch failed: %s", exc)
            with suppress(Exception):
                await api_core.close()  # type: ignore[possibly-undefined]

    # Log impact sets (including new method field) for observability
    if change_detail and change_detail.get("impact_sets"):
        for impact in change_detail["impact_sets"]:
            logger.info(
                "Impact: %s", _format_impact_line(impact)
            )

    # -- Fetch billing summary ------------------------------------------------
    billing_summary: dict | None = None
    try:
        billing = BillingClient()
        billing_summary = await billing.get_billing_summary()
        await billing.close()
    except Exception as exc:
        logger.warning("Billing fetch failed: %s", exc)
        with suppress(Exception):
            await billing.close()  # type: ignore[possibly-undefined]

    # -- Jira: add comment to every ticket for this change --------------------
    tickets_result = await db.execute(
        select(JiraTicket).where(JiraTicket.change_id == event.change_id)
    )
    tickets = list(tickets_result.scalars().all())

    if tickets:
        try:
            jira = JiraClient()
            comment_doc = build_recovery_comment(event, billing_summary)
            for ticket in tickets:
                try:
                    await jira.add_comment(ticket.jira_issue_key, comment_doc)
                except Exception as exc:
                    logger.error(
                        "Jira comment failed for %s: %s",
                        ticket.jira_issue_key,
                        exc,
                    )
                    errors.append(f"jira_comment:{ticket.jira_issue_key}: {exc}")
            record.jira_sent = True
            await jira.close()
        except Exception as exc:
            logger.error("Jira client init failed: %s", exc)
            record.jira_error = str(exc)[:500]
            errors.append(f"jira: {exc}")
            with suppress(Exception):
                await jira.close()  # type: ignore[possibly-undefined]
    else:
        logger.info(
            "No Jira tickets found for change %d — skipping Jira comments",
            event.change_id,
        )

    # -- Slack: send recovery report ------------------------------------------
    try:
        slack = SlackClient()
        blocks = build_recovery_report(event, billing_summary)
        await slack.send_message(blocks)
        record.slack_sent = True
        await slack.close()
    except Exception as exc:
        logger.error(
            "Slack recovery report failed for change %d: %s",
            event.change_id,
            exc,
        )
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
        slack_sent=record.slack_sent,
        errors=errors,
    )
