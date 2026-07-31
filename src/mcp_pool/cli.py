import asyncio
from typing import Annotated

import typer
import uvicorn
from sqlalchemy import select

from mcp_pool.auth import hash_password
from mcp_pool.config import get_settings
from mcp_pool.db import UserModel, async_session

app = typer.Typer(help="MCPPool command line interface.", no_args_is_help=False)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    host: Annotated[str | None, typer.Option(help="Address to bind.")] = None,
    port: Annotated[int | None, typer.Option(help="Port to bind.")] = None,
    reload: Annotated[bool, typer.Option(help="Enable development reload.")] = False,
) -> None:
    """Run the MCPPool gateway."""
    if ctx.invoked_subcommand is None:
        settings = get_settings()
        uvicorn.run(
            "mcp_pool.app:create_app",
            factory=True,
            host=host or settings.host,
            port=port or settings.port,
            reload=reload,
            log_level=settings.log_level.lower(),
        )


@app.command("serve")
def serve(
    host: Annotated[str | None, typer.Option(help="Address to bind.")] = None,
    port: Annotated[int | None, typer.Option(help="Port to bind.")] = None,
    reload: Annotated[bool, typer.Option(help="Enable development reload.")] = False,
) -> None:
    """Run the MCPPool gateway."""
    settings = get_settings()
    uvicorn.run(
        "mcp_pool.app:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


async def _reset_user_password(username: str, password: str) -> bool:
    async with async_session() as session:
        result = await session.execute(select(UserModel).where(UserModel.username == username))
        user = result.scalar_one_or_none()
        if user is None:
            return False
        user.password_hash = hash_password(password)
        user.token_version = (user.token_version or 0) + 1
        await session.commit()
        return True


@app.command("reset-password")
def reset_password(username: Annotated[str, typer.Argument(help="Username to update.")]) -> None:
    """Replace a user's password with a versioned scrypt hash."""
    password = typer.prompt("New password", hide_input=True, confirmation_prompt=True)
    if not password:
        raise typer.BadParameter("Password must not be empty")
    if not asyncio.run(_reset_user_password(username, password)):
        typer.echo(f"User '{username}' was not found", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Password reset for '{username}'; existing access tokens were revoked")


if __name__ == "__main__":
    app()
