from typing import Annotated

import typer
import uvicorn

from mcp_pool.config import get_settings

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


if __name__ == "__main__":
    app()
