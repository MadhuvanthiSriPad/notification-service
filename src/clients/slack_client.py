"""Slack Web API client (Bot token, Block Kit)."""

from __future__ import annotations

import logging

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

_SLACK_POST_MESSAGE = "https://slack.com/api/chat.postMessage"


class SlackClient:
    """Send messages via Slack Web API."""

    def __init__(self) -> None:
        if not settings.slack_bot_token or not settings.slack_channel:
            raise RuntimeError("Slack not configured — set NOTIF_SLACK_BOT_TOKEN and NOTIF_SLACK_CHANNEL")
        self._headers = {
            "Authorization": f"Bearer {settings.slack_bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        self._channel = settings.slack_channel
        self._client = httpx.AsyncClient(timeout=10.0)

    async def send_message(self, blocks: list[dict], text: str = "") -> dict:
        """Post a Block Kit message to the configured channel.

        Returns the Slack API response JSON.
        """
        payload = {
            "channel": self._channel,
            "blocks": blocks,
            "text": text or "Remediation PR notification",
        }
        resp = await self._client.post(
            _SLACK_POST_MESSAGE, json=payload, headers=self._headers
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            logger.error("Slack API error: %s", data.get("error"))
        else:
            logger.info("Slack message sent to %s", self._channel)
        return data

    async def close(self) -> None:
        await self._client.aclose()
