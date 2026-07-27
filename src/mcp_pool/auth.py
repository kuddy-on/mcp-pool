import base64
import hashlib
import hmac
import json
import time
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel

from mcp_pool.config import get_settings


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


def hash_password(password: str) -> str:
    settings = get_settings()
    salted = f"{password}:{settings.secret_key.get_secret_value()}"
    return hashlib.sha256(salted.encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hash_password(plain_password) == hashed_password


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(data_str: str) -> bytes:
    padding = "=" * (4 - (len(data_str) % 4))
    return base64.urlsafe_b64decode((data_str + padding).encode("ascii"))


def create_access_token(user: UserDTO, expires_in_days: int = 30) -> str:
    """Create a stateless HMAC-SHA256 JWT token."""
    settings = get_settings()
    secret = settings.secret_key.get_secret_value().encode("utf-8")

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "exp": int(time.time()) + (expires_in_days * 86400),
    }

    header_b64 = _base64url_encode(json.dumps(header).encode("utf-8"))
    payload_b64 = _base64url_encode(json.dumps(payload).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode()

    signature = hmac.new(secret, signing_input, hashlib.sha256).digest()
    sig_b64 = _base64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_access_token(token: str) -> UserDTO:
    """Verify and decode a stateless HMAC-SHA256 JWT token."""
    settings = get_settings()
    secret = settings.secret_key.get_secret_value().encode("utf-8")

    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format",
        )

    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode()
    expected_sig = hmac.new(secret, signing_input, hashlib.sha256).digest()
    actual_sig = _base64url_decode(sig_b64)

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signature",
        )

    try:
        payload = json.loads(_base64url_decode(payload_b64).decode("utf-8"))
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        ) from err

    if payload.get("exp") and time.time() > payload["exp"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )

    return UserDTO(
        id=payload["sub"],
        username=payload["username"],
        role=payload["role"],
    )


# Keep active_tokens for backwards compatibility in tests if referenced
active_tokens: dict[str, UserDTO] = {}


def get_current_user(authorization: Annotated[str | None, Header()] = None) -> UserDTO:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    token = authorization.replace("Bearer ", "").strip()
    # First check active_tokens (in case legacy token used in tests)
    if token in active_tokens:
        return active_tokens[token]
    # Stateless JWT decode
    return decode_access_token(token)


def require_admin(user: Annotated[UserDTO, Depends(get_current_user)]) -> UserDTO:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user
