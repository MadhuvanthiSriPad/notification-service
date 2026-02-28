"""Webhook routes for notification-service."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.handlers.event_handler import handle_pr_opened
from src.schemas.events import PROpenedEvent, WebhookResponse

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
