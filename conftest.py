"""Shared test configuration — must be loaded before src modules."""

import os

# Override database URL before any src modules are imported.
os.environ["NOTIF_DATABASE_URL"] = "sqlite+aiosqlite://"

import pytest
from src.database import engine, Base


@pytest.fixture(autouse=True)
async def _reset_db():
    """Create all tables before each test, drop after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
