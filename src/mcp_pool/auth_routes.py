import asyncio
import math
import time
from collections import OrderedDict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from mcp_pool.auth import (
    LoginRequest,
    LoginResponse,
    UserCreateRequest,
    UserDTO,
    create_access_token,
    get_current_user,
    hash_password,
    password_hash_needs_upgrade,
    require_admin,
    verify_password,
)
from mcp_pool.config import get_settings
from mcp_pool.db import UserModel, async_session

router = APIRouter(prefix="/api", tags=["auth"])
_login_failures: OrderedDict[str, list[float]] = OrderedDict()
_login_failures_lock = asyncio.Lock()


def _login_client_id(request: Request, username: str) -> str:
    settings = get_settings()
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    address = (
        forwarded
        if settings.trust_proxy_headers and forwarded
        else request.client.host
        if request.client
        else "unknown"
    )
    return f"{address}:{username.casefold()}"


async def _login_retry_after(client_id: str) -> int:
    settings = get_settings()
    now = time.monotonic()
    cutoff = now - settings.login_attempt_window_seconds
    async with _login_failures_lock:
        attempts = [attempt for attempt in _login_failures.get(client_id, []) if attempt >= cutoff]
        if attempts:
            _login_failures[client_id] = attempts
            _login_failures.move_to_end(client_id)
        else:
            _login_failures.pop(client_id, None)
        if len(attempts) < settings.login_attempt_limit:
            return 0
        return max(1, math.ceil(settings.login_attempt_window_seconds - (now - attempts[0])))


async def _record_login_failure(client_id: str) -> int:
    settings = get_settings()
    now = time.monotonic()
    async with _login_failures_lock:
        if (
            client_id not in _login_failures
            and len(_login_failures) >= settings.login_attempt_max_entries
        ):
            cutoff = now - settings.login_attempt_window_seconds
            expired = [
                known_id
                for known_id, attempts in _login_failures.items()
                if not attempts or attempts[-1] < cutoff
            ]
            for known_id in expired:
                _login_failures.pop(known_id, None)
            while len(_login_failures) >= settings.login_attempt_max_entries:
                _login_failures.popitem(last=False)
        _login_failures.setdefault(client_id, []).append(now)
        _login_failures.move_to_end(client_id)
    return await _login_retry_after(client_id)


async def _clear_login_failures(client_id: str) -> None:
    async with _login_failures_lock:
        _login_failures.pop(client_id, None)


@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request) -> LoginResponse:
    client_id = _login_client_id(request, req.username)
    retry_after = await _login_retry_after(client_id)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
            headers={"Retry-After": str(retry_after)},
        )
    async with async_session() as session:
        stmt = select(UserModel).where(UserModel.username == req.username)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()

        if not user or not verify_password(req.password, user.password_hash):
            retry_after = await _record_login_failure(client_id)
            if retry_after:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many login attempts",
                    headers={"Retry-After": str(retry_after)},
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
            )
        if password_hash_needs_upgrade(user.password_hash):
            user.password_hash = hash_password(req.password)
            await session.commit()
        await _clear_login_failures(client_id)

        user_dto = UserDTO(id=user.id, username=user.username, role=user.role)
        token = create_access_token(
            user_dto,
            token_version=user.token_version or 0,
        )

        return LoginResponse(token=token, user=user_dto)


@router.get("/auth/me", response_model=UserDTO)
async def get_me(current_user: Annotated[UserDTO, Depends(get_current_user)]) -> UserDTO:
    return current_user


@router.post("/auth/logout")
async def logout(
    current_user: Annotated[UserDTO, Depends(get_current_user)],
) -> dict[str, str]:
    async with async_session() as session:
        result = await session.execute(select(UserModel).where(UserModel.id == current_user.id))
        user = result.scalar_one_or_none()
        if user is not None:
            user.token_version = (user.token_version or 0) + 1
            await session.commit()
    return {"status": "ok"}


@router.get("/admin/users", response_model=list[UserDTO])
async def list_users(admin: Annotated[UserDTO, Depends(require_admin)]) -> list[UserDTO]:
    async with async_session() as session:
        stmt = select(UserModel)
        res = await session.execute(stmt)
        users = res.scalars().all()
        return [UserDTO(id=u.id, username=u.username, role=u.role) for u in users]


@router.post("/admin/users", response_model=UserDTO)
async def create_user(
    req: UserCreateRequest, admin: Annotated[UserDTO, Depends(require_admin)]
) -> UserDTO:
    async with async_session() as session:
        stmt = select(UserModel).where(UserModel.username == req.username)
        res = await session.execute(stmt)
        if res.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Username already exists")

        new_usr = UserModel(
            username=req.username,
            password_hash=hash_password(req.password),
            role=req.role,
        )
        session.add(new_usr)
        await session.commit()
        await session.refresh(new_usr)

        return UserDTO(id=new_usr.id, username=new_usr.username, role=new_usr.role)


@router.delete("/admin/users/{user_id}")
async def delete_user(
    user_id: str, admin: Annotated[UserDTO, Depends(require_admin)]
) -> dict[str, str]:
    if admin.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete current admin user")

    async with async_session() as session:
        stmt = select(UserModel).where(UserModel.id == user_id)
        res = await session.execute(stmt)
        u = res.scalar_one_or_none()
        if u:
            await session.delete(u)
            await session.commit()
            return {"status": "ok"}
    raise HTTPException(status_code=404, detail="User not found")
