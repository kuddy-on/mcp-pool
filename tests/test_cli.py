import uvicorn
from pytest import MonkeyPatch
from typer.testing import CliRunner

from mcp_pool import cli


def test_serve_command_forwards_explicit_options(monkeypatch: MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_run(application: str, **kwargs: object) -> None:
        calls.append((application, kwargs))

    monkeypatch.setattr(uvicorn, "run", fake_run)
    result = CliRunner().invoke(
        cli.app,
        ["serve", "--host", "0.0.0.0", "--port", "9000", "--reload"],
    )

    assert result.exit_code == 0
    assert calls == [
        (
            "mcp_pool.app:create_app",
            {
                "factory": True,
                "host": "0.0.0.0",
                "port": 9000,
                "reload": True,
                "log_level": "info",
            },
        )
    ]


def test_default_command_uses_settings(monkeypatch: MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(application: str, **kwargs: object) -> None:
        assert application == "mcp_pool.app:create_app"
        calls.append(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    result = CliRunner().invoke(cli.app, [])

    assert result.exit_code == 0
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 8000
