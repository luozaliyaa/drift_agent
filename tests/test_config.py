from __future__ import annotations

from pathlib import Path

from drift_agent.config import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    load_deepseek_config,
    load_dotenv,
)


def test_load_deepseek_config_defaults(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)

    config = load_deepseek_config()

    assert config.api_key is None
    assert config.model == DEFAULT_DEEPSEEK_MODEL == "deepseek-v4-pro"
    assert config.base_url == DEFAULT_DEEPSEEK_BASE_URL == "https://api.deepseek.com"
    assert not config.is_configured


def test_load_dotenv_sets_missing_values(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    env_file = Path(".pytest-tmp") / "test.env"
    env_file.parent.mkdir(exist_ok=True)
    env_file.write_text("DEEPSEEK_API_KEY=sk-test\n", encoding="utf-8")

    try:
        load_dotenv(env_file)

        assert load_deepseek_config().api_key == "sk-test"
    finally:
        env_file.unlink(missing_ok=True)
