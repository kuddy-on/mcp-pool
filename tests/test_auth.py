from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi import HTTPException

from mcp_pool.app import create_app, lifespan
from mcp_pool.auth import (
    JWT_AUDIENCE,
    JWT_ISSUER,
    UserDTO,
    _jwt_signing_key,
    create_access_token,
    decode_access_token,
)


def test_access_token_round_trip() -> None:
    user = UserDTO(id="user-1", username="alice", role="admin")

    token = create_access_token(user, token_version=3)
    claims = decode_access_token(token)

    assert claims.id == user.id
    assert claims.username == user.username
    assert claims.role == user.role
    assert claims.token_version == 3


def test_access_token_rejects_expired_token() -> None:
    token = create_access_token(
        UserDTO(id="user-1", username="alice", role="admin"),
        token_version=0,
        expires_in_days=-1,
    )

    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(token)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Token has expired"


@pytest.mark.parametrize("token", ["not-a-jwt", "a.b.c", ""])
def test_access_token_rejects_malformed_tokens(token: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(token)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid access token"


def test_access_token_rejects_wrong_algorithm_and_missing_claims() -> None:
    now = datetime.now(UTC)
    wrong_algorithm = jwt.encode(
        {
            "sub": "user-1",
            "username": "alice",
            "role": "admin",
            "token_version": 0,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
        },
        b"x" * 48,
        algorithm="HS384",
    )
    missing_expiry = jwt.encode(
        {
            "sub": "user-1",
            "username": "alice",
            "role": "admin",
            "token_version": 0,
            "iat": now,
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
        },
        _jwt_signing_key(),
        algorithm="HS256",
    )

    for token in (wrong_algorithm, missing_expiry):
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(token)
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid access token"


@pytest.mark.asyncio
async def test_logout_revokes_existing_token() -> None:
    app = create_app()

    async with (
        lifespan(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        login_response = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert login_response.status_code == 200
        token = login_response.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        assert (await client.get("/api/auth/me", headers=headers)).status_code == 200
        assert (await client.post("/api/auth/logout", headers=headers)).status_code == 200

        revoked_response = await client.get("/api/auth/me", headers=headers)
        assert revoked_response.status_code == 401
        assert revoked_response.json()["detail"] == "Access token has been revoked"


@pytest.mark.asyncio
async def test_login_rate_limit_blocks_repeated_failures() -> None:
    app = create_app()
    username = f"missing-{uuid4().hex}"

    async with (
        lifespan(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        responses = [
            await client.post(
                "/api/auth/login",
                json={"username": username, "password": "definitely-wrong"},
            )
            for _ in range(5)
        ]
        blocked = await client.post(
            "/api/auth/login",
            json={"username": username, "password": "definitely-wrong"},
        )

    assert [response.status_code for response in responses[:4]] == [401] * 4
    assert responses[4].status_code == 429
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0
