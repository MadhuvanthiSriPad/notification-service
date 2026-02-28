"""FastAPI application for notification-service."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.database import init_db, close_db
from src.routes.webhooks import router as webhooks_router

logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("notification-service starting up")
    await init_db()
    yield
    logger.info("notification-service shutting down")
    await close_db()


app = FastAPI(
    title="Notification Service",
    description="Jira ticket creation and Slack notifications for ACCR remediation PRs",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhooks_router, prefix=settings.api_prefix)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "notification-service"}
