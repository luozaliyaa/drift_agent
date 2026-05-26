from __future__ import annotations

from drift_agent.cli import main


def test_cli_smoke_success(capsys) -> None:
    exit_code = main(["write tests", "--mode", "stub"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "status: success" in captured.out
    assert "trace:" in captured.out


def test_cli_live_mode_requires_api_key(capsys, monkeypatch) -> None:
    monkeypatch.setattr("drift_agent.cli.load_dotenv", lambda: None)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    exit_code = None
    try:
        main(["write tests", "--mode", "live"])
    except SystemExit as exc:
        exit_code = exc.code

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "DEEPSEEK_API_KEY is required" in captured.err
