from __future__ import annotations

from drift_agent.cli import main


def test_cli_smoke_success(capsys) -> None:
    exit_code = main(["write tests"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "status: success" in captured.out
    assert "trace:" in captured.out
