"""HTTP clients for the billing service and api-core session tracking."""

from __future__ import annotations

import logging

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


class BillingClient:
    """Fetch billing summary data from the billing service."""

    def __init__(self) -> None:
        self._base_url = settings.billing_url.rstrip("/") if settings.billing_url else ""
        self._client = httpx.AsyncClient(timeout=15.0)

    async def get_billing_summary(self) -> dict | None:
        """Return platform billing summary, or None if unavailable."""
        if not self._base_url:
            logger.info("Billing URL not configured — skipping billing enrichment")
            return None
        url = f"{self._base_url}/api/v1/billing/summary"
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Failed to fetch billing summary: %s", exc)
            return None

    async def close(self) -> None:
        await self._client.aclose()


class ApiCoreClient:
    """Create and manage sessions on api-core.

    All POST /api/v1/sessions calls include the required ``data_residency``
    field (enum: 'us', 'eu', 'ap') introduced by the upstream breaking
    contract change.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (base_url or settings.api_core_url).rstrip("/")
        if not self._base_url:
            raise RuntimeError(
                "api-core URL not configured — set NOTIF_API_CORE_URL"
            )
        self._client = httpx.AsyncClient(timeout=15.0)

    async def create_session(
        self,
        team_id: str,
        agent_name: str,
        priority: str = "medium",
        data_residency: str | None = None,
        prompt: str | None = None,
        tags: str | None = None,
    ) -> dict:
        """POST /api/v1/sessions on api-core.

        The ``data_residency`` field is required by api-core.  If not
        supplied explicitly it falls back to
        ``settings.default_data_residency`` (default ``"us"``).

        Returns the session response dict from api-core.
        """
        url = f"{self._base_url}/api/v1/sessions"
        payload: dict = {
            "team_id": team_id,
            "agent_name": agent_name,
            "priority": priority,
            "data_residency": data_residency or settings.default_data_residency,
        }
        if prompt is not None:
            payload["prompt"] = prompt
        if tags is not None:
            payload["tags"] = tags

        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        logger.info(
            "api-core session created: %s (data_residency=%s)",
            data.get("session_id", "?"),
            payload["data_residency"],
        )
        return data

    async def get_change_detail(self, change_id: int) -> dict | None:
        """GET /api/v1/contracts/changes/{change_id} — best-effort."""
        url = f"{self._base_url}/api/v1/contracts/changes/{change_id}"
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning(
                "Failed to fetch change detail for change_id=%d: %s",
                change_id,
                exc,
            )
            return None

    async def close(self) -> None:
        await self._client.aclose()
