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

    async def _post(self, payload: dict) -> dict:
        """Send one chat.postMessage request and return the response JSON."""
        resp = await self._client.post(
            _SLACK_POST_MESSAGE, json=payload, headers=self._headers
        )
        resp.raise_for_status()
        return resp.json()

    async def send_message(self, blocks: list[dict] | None = None, text: str = "") -> dict:
        """Post a message to the configured channel."""
        payload = {
            "channel": self._channel,
            "text": text or "Remediation PR notification",
        }
        if blocks:
            payload["blocks"] = blocks

        data = await self._post(payload)
        error_code = data.get("error", "unknown_error")
        if not data.get("ok") and blocks and error_code == "invalid_blocks":
            logger.warning("Slack rejected blocks; retrying with text-only fallback")
            data = await self._post({
                "channel": self._channel,
                "text": text or "Remediation PR notification",
            })
            error_code = data.get("error", error_code)

        if not data.get("ok"):
            logger.error("Slack API error: %s", error_code)
            raise RuntimeError(f"Slack API error: {error_code}")
        logger.info("Slack message sent to %s", self._channel)
        return data

    async def close(self) -> None:
        await self._client.aclose()
