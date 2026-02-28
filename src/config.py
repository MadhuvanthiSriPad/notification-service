"""Configuration for notification-service."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./notification.db"
    api_prefix: str = "/api/v1"
    debug: bool = False

    # Jira Cloud
    jira_base_url: str = ""
    jira_user_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = "ACCR"
    jira_assignee_account_id: str = ""

    # Slack
    slack_bot_token: str = ""
    slack_channel: str = ""

    model_config = {"env_prefix": "NOTIF_"}


settings = Settings()
