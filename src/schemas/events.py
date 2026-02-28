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


class JobSummary(BaseModel):
    job_id: int
    target_repo: str = ""
    target_service: str = ""
    pr_url: str = ""
    started_at: str = ""
    resolved_at: str = ""


class RecoveryCompleteEvent(BaseModel):
    event_type: str = "recovery_complete"
    change_id: int
    timestamp: str
    severity: str = "high"
    is_breaking: bool = True
    summary: str = ""
    affected_services: list[str] = []
    changed_routes: list[str] = []
    total_jobs: int = 0
    jobs: list[JobSummary] = []
    mttr_seconds: int = 0


class WebhookResponse(BaseModel):
    status: str
    jira_issue_key: Optional[str] = None
    jira_issue_url: Optional[str] = None
    slack_sent: Optional[bool] = None
    errors: list[str] = []
