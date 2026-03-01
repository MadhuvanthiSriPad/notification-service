"""Pydantic models for webhook payloads."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DevinContext(BaseModel):
    """Relevant context extracted from the Devin remediation prompt."""

    brief: str = ""
    mission: str = ""
    affected_endpoints: list[str] = Field(default_factory=list)
    technical_details: list[str] = Field(default_factory=list)
    key_files: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)


class NotificationAssertions(BaseModel):
    """Machine-checkable assertions emitted by Devin for notifications."""

    source_repo: str = ""
    target_repo: str = ""
    target_service: str = ""
    pr_url: str = ""


class NotificationJiraBundle(BaseModel):
    """Devin-authored Jira content."""

    summary: str = ""
    description_text: str = ""
    description_adf: dict | None = None


class NotificationSlackBundle(BaseModel):
    """Devin-authored Slack content."""

    text: str = ""
    blocks: list[dict] = Field(default_factory=list)


class NotificationBundle(BaseModel):
    """Optional notification copy authored by Devin."""

    model_config = ConfigDict(extra="ignore")

    author: str = "devin"
    assertions: NotificationAssertions = Field(default_factory=NotificationAssertions)
    jira: NotificationJiraBundle = Field(default_factory=NotificationJiraBundle)
    slack: NotificationSlackBundle = Field(default_factory=NotificationSlackBundle)


class PROpenedEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_type: str = "pr_opened"
    change_id: int
    job_id: int
    timestamp: datetime
    source_repo: str = "api-core"
    target_repo: str
    target_service: str
    pr_url: str
    devin_session_url: str
    severity: str = "high"
    is_breaking: bool = True
    summary: str = ""
    changed_routes: list[str] = Field(default_factory=list)
    devin_context: DevinContext = Field(default_factory=DevinContext)
    notification_bundle: NotificationBundle | None = None


class JobSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: int
    target_repo: str = ""
    target_service: str = ""
    pr_url: str = ""
    devin_session_url: str = ""
    started_at: str = ""
    resolved_at: str = ""


class RecoveryCompleteEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_type: str = "recovery_complete"
    change_id: int
    timestamp: str
    source_repo: str = "api-core"
    severity: str = "high"
    is_breaking: bool = True
    summary: str = ""
    affected_services: list[str] = Field(default_factory=list)
    changed_routes: list[str] = Field(default_factory=list)
    total_jobs: int = 0
    jobs: list[JobSummary] = Field(default_factory=list)
    mttr_seconds: int = 0


class WebhookResponse(BaseModel):
    status: str
    jira_issue_key: Optional[str] = None
    jira_issue_url: Optional[str] = None
    slack_sent: Optional[bool] = None
    errors: list[str] = Field(default_factory=list)
