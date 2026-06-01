from __future__ import annotations

import json

from drift_agent.mcp.config import load_mcp_config


def test_load_mcp_config_supports_object_form(tmp_path) -> None:
    path = tmp_path / "mcp_servers.json"
    path.write_text(
        json.dumps(
            {
                "servers": {
                    "github": {
                        "command": "github-mcp-server",
                        "args": ["stdio"],
                        "env": {"GITHUB_TOKEN": "token"},
                        "timeout_seconds": 3,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_mcp_config(path)
    server = config.get("github")

    assert server is not None
    assert server.command == "github-mcp-server"
    assert server.args == ("stdio",)
    assert server.env == {"GITHUB_TOKEN": "token"}
    assert server.timeout_seconds == 3


def test_load_mcp_config_supports_list_form_and_skips_bad_entries(tmp_path) -> None:
    path = tmp_path / "mcp_servers.json"
    path.write_text(
        json.dumps(
            {
                "servers": [
                    {"name": "github", "command": "github-mcp-server"},
                    {"name": "missing-command"},
                ]
            }
        ),
        encoding="utf-8",
    )

    config = load_mcp_config(path)

    assert sorted(config.servers) == ["github"]
