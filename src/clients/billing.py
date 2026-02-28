"""HTTP clients for the billing service and api-core contract details."""

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
    """Fetch contract change details from api-core.

    The response includes ``impact_sets`` whose items now contain a
    ``method`` field (nullable string) introduced by the upstream API
    change.  This client passes the full response through so callers
    can access all fields including ``method``.
    """

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=15.0)

    async def get_change_detail(self, change_id: int) -> dict | None:
        """GET /api/v1/contracts/changes/{change_id} and return the JSON.

        Returns None on any failure so the caller can degrade gracefully.
        The returned dict includes ``impact_sets`` — a list of dicts each
        containing at least ``caller_service``, ``route_template``,
        ``method`` (str | None), ``calls_last_7d``, ``confidence``, and
        ``notes``.
        """
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
