"""Pydantic models for webhook payloads."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PROpenedEvent(BaseModel):
    event_type: str = "pr_opened"
    change_id: int
    job_id: int
    timestamp: datetime
    target_repo: str
    target_service: str
    pr_url: str
    devin_session_url: str
    severity: str = "high"
    is_breaking: bool = True
    summary: str = ""
    changed_routes: list[str] = []


class WebhookResponse(BaseModel):
    status: str
    jira_issue_key: Optional[str] = None
    jira_issue_url: Optional[str] = None
    slack_sent: Optional[bool] = None
    errors: list[str] = []
