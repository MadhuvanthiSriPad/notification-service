"""Jira Cloud REST API client (Basic auth)."""

from __future__ import annotations

import base64
import logging

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


class JiraClient:
    """Create issues via Jira Cloud REST API v3."""

    def __init__(self) -> None:
        if not settings.jira_base_url or not settings.jira_api_token:
            raise RuntimeError("Jira not configured — set NOTIF_JIRA_BASE_URL and NOTIF_JIRA_API_TOKEN")
        credentials = base64.b64encode(
            f"{settings.jira_user_email}:{settings.jira_api_token}".encode()
        ).decode()
        self._base_url = settings.jira_base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._client = httpx.AsyncClient(timeout=15.0)

    async def create_issue(self, fields: dict) -> dict:
        """Create a Jira issue and return the response JSON.

        Returns dict with at least 'key' and 'self' on success.
        """
        url = f"{self._base_url}/rest/api/3/issue"
        payload = {"fields": fields}
        resp = await self._client.post(url, json=payload, headers=self._headers)
        resp.raise_for_status()
        data = resp.json()
        logger.info("Jira issue created: %s", data.get("key"))
        return data

    async def add_comment(self, issue_key: str, body_doc: dict) -> dict:
        """Add an ADF comment to an existing Jira issue."""
        url = f"{self._base_url}/rest/api/3/issue/{issue_key}/comment"
        resp = await self._client.post(url, json={"body": body_doc}, headers=self._headers)
        resp.raise_for_status()
        logger.info("Jira comment added to %s", issue_key)
        return resp.json()

    def browse_url(self, issue_key: str) -> str:
        return f"{self._base_url}/browse/{issue_key}"

    async def close(self) -> None:
        await self._client.aclose()
