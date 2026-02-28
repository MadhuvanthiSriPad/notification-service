"""Idempotency tracking for webhook events."""

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime

from src.database import Base


class NotificationEvent(Base):
    __tablename__ = "notification_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    idempotency_key = Column(String, unique=True, nullable=False, index=True)
    event_type = Column(String, nullable=False)
    change_id = Column(Integer, nullable=False)
    job_id = Column(Integer, nullable=False)
    payload_json = Column(Text, nullable=False)
    jira_sent = Column(Boolean, default=False, nullable=False)
    jira_error = Column(Text, nullable=True)
    slack_sent = Column(Boolean, default=False, nullable=False)
    slack_error = Column(Text, nullable=True)
    received_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
