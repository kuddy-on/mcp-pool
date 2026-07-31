import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from mcp_pool.app import create_app
from mcp_pool.db import _configure_sqlite_connection, async_session, init_db


def test_liveness() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(response.headers["x-request-id"]) == 36


def test_readiness() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_schema_migrations_record_version_and_create_usage_index() -> None:
    await init_db()

    async with async_session() as session:
        versions = await session.execute(
            text("SELECT version FROM schema_migrations ORDER BY version")
        )
        indexes = await session.execute(text("PRAGMA index_list('request_logs')"))

    assert [row[0] for row in versions] == [1, 2]
    assert "ix_request_logs_timestamp_key_id" in {row[1] for row in indexes}


def test_sqlite_connection_pragmas_apply_to_every_connection() -> None:
    connections = [sqlite3.connect(":memory:"), sqlite3.connect(":memory:")]
    try:
        for connection in connections:
            _configure_sqlite_connection(connection, None)
            assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
            assert connection.execute("PRAGMA busy_timeout").fetchone() == (5000,)
    finally:
        for connection in connections:
            connection.close()
