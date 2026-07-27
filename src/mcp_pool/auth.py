import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from mcp_pool.config import get_settings
from mcp_pool.db import UserModel, async_session

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "mcp-pool"
JWT_AUDIENCE = "mcp-pool-api"
JWT_KEY_CONTEXT = b"mcp-pool:jwt-signing:v1"
REQUIRED_JWT_CLAIMS = [
    "exp",
    "iat",
    "iss",
    "aud",
    "sub",
    "username",
    "role",
    "token_version",
]
bearer_scheme = HTTPBearer(auto_error=False)


class UserDTO(BaseModel):
    id: str
    username: str
    role: str  # "admin" or "user"


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user: UserDTO


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "user"


class AccessTokenClaims(UserDTO):
    token_version: int


def hash_password(password: str) -> str:
    settings = get_settings()
    salted = f"{password}:{settings.secret_key.get_secret_value()}"
    return hashlib.sha256(salted.encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hmac.compare_digest(hash_password(plain_password), hashed_password)


def _jwt_signing_key() -> bytes:
    application_secret = get_settings().secret_key.get_secret_value().encode("utf-8")
    return hmac.new(application_secret, JWT_KEY_CONTEXT, hashlib.sha256).digest()


def create_access_token(
    user: UserDTO,
    *,
    token_version: int,
    expires_in_days: int = 30,
) -> str:
    """Create a signed access token with explicit issuer, audience, and expiry claims."""
    now = datetime.now(UTC)
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "token_version": token_version,
        "iat": now,
        "exp": now + timedelta(days=expires_in_days),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
    }
    return jwt.encode(
        payload,
        _jwt_signing_key(),
        algorithm=JWT_ALGORITHM,
    )


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def decode_access_token(token: str) -> AccessTokenClaims:
    """Verify a JWT using PyJWT and return its validated application claims."""
    try:
        payload = jwt.decode(
            token,
            _jwt_signing_key(),
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
            options={"require": REQUIRED_JWT_CLAIMS},
        )
        return AccessTokenClaims.model_validate(
            {
                "id": payload["sub"],
                "username": payload["username"],
                "role": payload["role"],
                "token_version": payload["token_version"],
            }
        )
    except ExpiredSignatureError as err:
        raise _unauthorized("Token has expired") from err
    except (InvalidTokenError, ValidationError) as err:
        raise _unauthorized("Invalid access token") from err


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> UserDTO:
    if credentials is None:
        raise _unauthorized("Missing Authorization header")

    claims = decode_access_token(credentials.credentials)
    async with async_session() as session:
        result = await session.execute(select(UserModel).where(UserModel.id == claims.id))
        user = result.scalar_one_or_none()

    if user is None or (user.token_version or 0) != claims.token_version:
        raise _unauthorized("Access token has been revoked")

    return UserDTO(id=user.id, username=user.username, role=user.role)


def require_admin(user: Annotated[UserDTO, Depends(get_current_user)]) -> UserDTO:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user
