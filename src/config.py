"""Configuration for notification-service."""

import json

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./notification.db"
    api_prefix: str = "/api/v1"
    debug: bool = False

    # Jira Cloud
    jira_base_url: str = ""
    jira_user_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = "AC"
    jira_project_keys_by_repo: dict[str, str] = {}
    jira_assignee_account_id: str = ""

    # Slack
    slack_bot_token: str = ""
    slack_channel: str = ""

    # api-core — used for session tracking and contract change details
    api_core_url: str = ""
    # Required data residency region for POST /api/v1/sessions (enum: us, eu, ap)
    default_data_residency: str = "us"

    # Billing service — used to enrich post-incident reports with platform cost data
    billing_url: str = ""

    model_config = {"env_prefix": "NOTIF_"}

    @field_validator("jira_project_keys_by_repo", mode="before")
    @classmethod
    def _parse_jira_project_keys_by_repo(cls, value: object) -> object:
        if value in (None, ""):
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            return json.loads(value)
        raise TypeError("jira_project_keys_by_repo must be a dict or JSON object string")


settings = Settings()
