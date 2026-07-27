from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from mcp_pool.auth import (
    LoginRequest,
    LoginResponse,
    UserCreateRequest,
    UserDTO,
    create_access_token,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,
)
from mcp_pool.db import UserModel, async_session

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest) -> LoginResponse:
    async with async_session() as session:
        stmt = select(UserModel).where(UserModel.username == req.username)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()

        if not user or not verify_password(req.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
            )

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
            role=req.role if req.role in ("admin", "user") else "user",
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
