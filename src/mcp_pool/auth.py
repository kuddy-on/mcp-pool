import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from pydantic import BaseModel, Field, ValidationError
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
PASSWORD_HASH_SCHEME = "scrypt"
PASSWORD_SCRYPT_N = 2**14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1
bearer_scheme = HTTPBearer(auto_error=False)


class UserDTO(BaseModel):
    id: str
    username: str
    role: str  # "admin" or "user"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    token: str
    user: UserDTO


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=1024)
    role: Literal["admin", "user"] = "user"


class AccessTokenClaims(UserDTO):
    token_version: int


def hash_password(password: str) -> str:
    """Hash a password with a memory-hard, independently salted KDF."""
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=32,
    )
    return (
        f"{PASSWORD_HASH_SCHEME}${PASSWORD_SCRYPT_N}${PASSWORD_SCRYPT_R}$"
        f"{PASSWORD_SCRYPT_P}${salt.hex()}${derived.hex()}"
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password.startswith(f"{PASSWORD_HASH_SCHEME}$"):
        return False
    try:
        _, n, r, p, salt_hex, digest_hex = hashed_password.split("$", 5)
        derived = hashlib.scrypt(
            plain_password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(digest_hex)),
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(derived.hex(), digest_hex)


def _jwt_signing_key() -> bytes:
    application_secret = get_settings().secret_key.get_secret_value().encode("utf-8")
    return hmac.new(application_secret, JWT_KEY_CONTEXT, hashlib.sha256).digest()


def create_access_token(
    user: UserDTO,
    *,
    token_version: int,
    expires_in_days: int = 1,
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
