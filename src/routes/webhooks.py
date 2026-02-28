"""Webhook routes for notification-service."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.handlers.event_handler import handle_pr_opened
from src.handlers.recovery_report import handle_recovery_complete
from src.schemas.events import PROpenedEvent, RecoveryCompleteEvent, WebhookResponse

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/pr-opened", response_model=WebhookResponse)
async def pr_opened_webhook(
    event: PROpenedEvent,
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    """Receive a PR-opened event from api-core.

    Creates a Jira ticket and sends a Slack notification.
    Idempotent — duplicate events for the same job_id are skipped.
    """
    return await handle_pr_opened(db, event)


@router.post("/webhooks/recovery-complete", response_model=WebhookResponse)
async def recovery_complete_webhook(
    event: RecoveryCompleteEvent,
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    """Receive a recovery_complete event from api-core.

    Fetches billing summary, sends a rich Slack post-incident report,
    and adds a resolution comment to every open Jira ticket for the change.
    Idempotent — duplicate events for the same change_id are skipped.
    """
    return await handle_recovery_complete(db, event)
