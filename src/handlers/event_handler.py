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

from src.clients.billing import ApiCoreClient
from src.clients.jira_client import JiraClient
from src.clients.slack_client import SlackClient
from src.config import settings
from src.models.notification_event import NotificationEvent
from src.models.jira_ticket import JiraTicket
from src.schemas.events import NotificationBundle, PROpenedEvent, WebhookResponse
from src.templates.jira_templates import build_issue_fields_from_notification_bundle
from src.templates.slack_templates import (
    build_pr_notification,
    build_pr_notification_from_bundle,
    build_pr_notification_text,
)

logger = logging.getLogger(__name__)


def _normalize_repo_url(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    if value.startswith(("https://github.com/", "http://github.com/")):
        return value.rstrip("/").removesuffix(".git").replace("http://", "https://", 1)
    if value.startswith("github.com/"):
        return f"https://{value.rstrip('/').removesuffix('.git')}"
    if "/" in value and " " not in value and value.count("/") == 1:
        return f"https://github.com/{value.rstrip('/').removesuffix('.git')}"
    return value


def _repo_from_pr_url(pr_url: str | None) -> str | None:
    if not pr_url or "github.com/" not in pr_url:
        return None
    tail = pr_url.split("github.com/", 1)[1]
    parts = tail.split("/")
    if len(parts) < 2:
        return None
    return f"https://github.com/{parts[0]}/{parts[1]}"


def _repo_name(raw: str | None) -> str:
    if not raw:
        return ""
    normalized = _normalize_repo_url(raw)
    return (normalized or raw).rstrip("/").split("/")[-1]


def _validate_notification_bundle(
    event: PROpenedEvent,
    bundle: NotificationBundle | None,
) -> NotificationBundle | None:
    if bundle is None:
        return None
    author = (bundle.author or "").strip().lower()
    if author and author != "devin":
        logger.warning("Ignoring notification bundle for job %d: unexpected author=%s", event.job_id, bundle.author)
        return None

    asserted_source = bundle.assertions.source_repo or event.source_repo
    if _repo_name(asserted_source) != _repo_name(event.source_repo):
        logger.warning("Ignoring notification bundle for job %d: source repo mismatch", event.job_id)
        return None

    asserted_target_repo = bundle.assertions.target_repo or event.target_repo
    if _normalize_repo_url(asserted_target_repo) != _normalize_repo_url(event.target_repo):
        logger.warning("Ignoring notification bundle for job %d: target repo mismatch", event.job_id)
        return None

    asserted_target_service = bundle.assertions.target_service or event.target_service
    if asserted_target_service.strip() != event.target_service.strip():
        logger.warning("Ignoring notification bundle for job %d: target service mismatch", event.job_id)
        return None

    asserted_pr_url = bundle.assertions.pr_url or event.pr_url
    if asserted_pr_url.strip() != event.pr_url.strip():
        logger.warning("Ignoring notification bundle for job %d: PR URL mismatch", event.job_id)
        return None

    pr_repo = _repo_from_pr_url(event.pr_url)
    if pr_repo and _normalize_repo_url(pr_repo) != _normalize_repo_url(event.target_repo):
        logger.warning("Ignoring notification bundle for job %d: event PR repo does not match target repo", event.job_id)
        return None

    return bundle


def _has_devin_jira_content(bundle: NotificationBundle | None) -> bool:
    return bool(bundle and (bundle.jira.description_text or bundle.jira.description_adf))


def _jira_bundle_error(event: PROpenedEvent, bundle: NotificationBundle | None) -> str:
    if event.notification_bundle is None:
        return "missing Devin-authored notification bundle"
    if bundle is None:
        return "invalid Devin-authored notification bundle"
    return "missing Devin-authored Jira description in notification bundle"


def _has_devin_slack_content(bundle: NotificationBundle | None) -> bool:
    return bool(bundle and (bundle.slack.text or bundle.slack.blocks))


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

    existing = await db.execute(
        select(NotificationEvent).where(NotificationEvent.idempotency_key == idem_key)
    )
    if existing.scalar_one_or_none() is not None:
        logger.info("Duplicate webhook for job %d — skipping", event.job_id)
        return WebhookResponse(status="already_processed")

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

    # Create a tracking session on api-core (includes required data_residency)
    if settings.api_core_url:
        try:
            api_core = ApiCoreClient()
            await api_core.create_session(
                team_id="notification-service",
                agent_name="pr-opened-handler",
                priority="high",
                data_residency=settings.default_data_residency,
                prompt=f"pr_opened for job_id={event.job_id} change_id={event.change_id}",
                tags=f"change_id:{event.change_id},job_id:{event.job_id}",
            )
            await api_core.close()
        except Exception as exc:
            logger.warning("Could not create tracking session on api-core: %s", exc)
            with suppress(Exception):
                await api_core.close()  # type: ignore[possibly-undefined]
    jira_issue_key: str | None = None
    jira_issue_url: str | None = None
    validated_bundle = _validate_notification_bundle(event, event.notification_bundle)

    try:
        if not _has_devin_jira_content(validated_bundle):
            raise ValueError(_jira_bundle_error(event, validated_bundle))
        jira = JiraClient()
        fields = build_issue_fields_from_notification_bundle(event, validated_bundle)
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

    try:
        slack = SlackClient()
        if _has_devin_slack_content(validated_bundle):
            blocks, fallback_text = build_pr_notification_from_bundle(
                event,
                validated_bundle,
                jira_issue_key,
                jira_issue_url,
            )
        else:
            blocks = build_pr_notification(event, jira_issue_key, jira_issue_url)
            fallback_text = build_pr_notification_text(event, jira_issue_key, jira_issue_url)
        await slack.send_message(blocks, text=fallback_text)
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
