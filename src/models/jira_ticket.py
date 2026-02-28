"""Maps remediation job to Jira issue."""

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime

from src.database import Base


class JiraTicket(Base):
    __tablename__ = "jira_tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    change_id = Column(Integer, nullable=False)
    job_id = Column(Integer, nullable=False)
    jira_issue_key = Column(String, nullable=False)
    jira_issue_url = Column(String, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
