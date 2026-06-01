from __future__ import annotations

from drift_agent.cli import main
from drift_agent.loop import AgentStatus, AgentState


def test_cli_smoke_success(capsys) -> None:
    exit_code = main(["write tests", "--mode", "stub"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "status: success" in captured.out
    assert "trace:" not in captured.out


def test_cli_without_task_starts_repl_and_exits(capsys, monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "")

    exit_code = main(["--mode", "stub"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "interactive mode" in captured.out


def test_cli_repl_runs_task_then_exits(capsys, monkeypatch) -> None:
    inputs = iter(["write tests", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(inputs))

    exit_code = main(["--mode", "stub"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "final: Completed: write tests" in captured.out


def test_cli_trace_can_be_printed(capsys) -> None:
    exit_code = main(["write tests", "--mode", "stub", "--trace"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "trace:" in captured.out


def test_cli_defaults_to_live_planner(capsys, monkeypatch) -> None:
    class FakeMemoryManager:
        def __init__(self, **kwargs):
            assert kwargs["memory_dir"] == ".memory"
            assert kwargs["session_id"] == "default"

    class FakeDeepSeekPlanner:
        def __init__(self, config, **kwargs):
            assert config.api_key == "sk-test"
            assert kwargs["max_tool_rounds"] == 8
            assert kwargs["permission_policy"].mode.value == "ask"
            assert isinstance(kwargs["memory_manager"], FakeMemoryManager)
            assert kwargs["show_memory"] is False

        def __call__(self, state: AgentState):
            from drift_agent.loop import StepResult

            return StepResult(
                action="fake-live",
                observation="called fake live planner",
                status=AgentStatus.SUCCESS,
                output="live answer",
            )

    monkeypatch.setattr("drift_agent.cli.load_dotenv", lambda: None)
    monkeypatch.setattr("drift_agent.cli.DeepSeekPlanner", FakeDeepSeekPlanner)
    monkeypatch.setattr("drift_agent.cli.MemoryManager", FakeMemoryManager)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    exit_code = main(["write tests"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "final: live answer" in captured.out


def test_cli_passes_permission_mode_to_live_planner(capsys, monkeypatch) -> None:
    class FakeMemoryManager:
        def __init__(self, **kwargs):
            pass

    class FakeDeepSeekPlanner:
        def __init__(self, config, **kwargs):
            assert kwargs["permission_policy"].mode.value == "deny"

        def __call__(self, state: AgentState):
            from drift_agent.loop import StepResult

            return StepResult(
                action="fake-live",
                observation="called fake live planner",
                status=AgentStatus.SUCCESS,
                output="live answer",
            )

    monkeypatch.setattr("drift_agent.cli.load_dotenv", lambda: None)
    monkeypatch.setattr("drift_agent.cli.DeepSeekPlanner", FakeDeepSeekPlanner)
    monkeypatch.setattr("drift_agent.cli.MemoryManager", FakeMemoryManager)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    exit_code = main(["write tests", "--permission-mode", "deny"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "final: live answer" in captured.out


def test_cli_passes_memory_options_to_live_planner(capsys, monkeypatch) -> None:
    class FakeMemoryManager:
        def __init__(self, **kwargs):
            assert kwargs["memory_dir"] == "custom-memory"
            assert kwargs["session_id"] == "project-a"
            assert kwargs["keep_count"] == 4
            assert kwargs["consolidation_min"] == 2
            assert kwargs["optimizer_interval_seconds"] == 30
            assert kwargs["optimize_now"] is True

    class FakeDeepSeekPlanner:
        def __init__(self, config, **kwargs):
            assert isinstance(kwargs["memory_manager"], FakeMemoryManager)
            assert kwargs["show_memory"] is True

        def __call__(self, state: AgentState):
            from drift_agent.loop import StepResult

            return StepResult(
                action="fake-live",
                observation="called fake live planner",
                status=AgentStatus.SUCCESS,
                output="live answer",
            )

    monkeypatch.setattr("drift_agent.cli.load_dotenv", lambda: None)
    monkeypatch.setattr("drift_agent.cli.DeepSeekPlanner", FakeDeepSeekPlanner)
    monkeypatch.setattr("drift_agent.cli.MemoryManager", FakeMemoryManager)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    exit_code = main(
        [
            "write tests",
            "--memory-dir",
            "custom-memory",
            "--session",
            "project-a",
            "--show-memory",
            "--memory-keep-count",
            "4",
            "--memory-consolidation-min",
            "2",
            "--memory-optimizer-interval-seconds",
            "30",
            "--memory-optimize-now",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "final: live answer" in captured.out


def test_cli_memory_off_does_not_create_memory_manager(capsys, monkeypatch) -> None:
    class FakeDeepSeekPlanner:
        def __init__(self, config, **kwargs):
            assert kwargs["memory_manager"] is None

        def __call__(self, state: AgentState):
            from drift_agent.loop import StepResult

            return StepResult(
                action="fake-live",
                observation="called fake live planner",
                status=AgentStatus.SUCCESS,
                output="live answer",
            )

    monkeypatch.setattr("drift_agent.cli.load_dotenv", lambda: None)
    monkeypatch.setattr("drift_agent.cli.DeepSeekPlanner", FakeDeepSeekPlanner)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    exit_code = main(["write tests", "--memory", "off"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "final: live answer" in captured.out


def test_cli_live_mode_requires_api_key(capsys, monkeypatch) -> None:
    monkeypatch.setattr("drift_agent.cli.load_dotenv", lambda: None)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    exit_code = None
    try:
        main(["write tests"])
    except SystemExit as exc:
        exit_code = exc.code

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "DEEPSEEK_API_KEY is required" in captured.err


def test_cli_proactive_once_emits_terminal_notice(capsys, monkeypatch) -> None:
    class FakeTick:
        def __init__(self, **kwargs):
            pass

        def run_once(self):
            from drift_agent.proactive.types import ProactiveDecision

            return ProactiveDecision("reply", message="proactive hello")

    monkeypatch.setattr("drift_agent.cli.ProactiveAgentTick", FakeTick)

    exit_code = main(["--mode", "stub", "--proactive-once"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "proactive hello" in captured.out


def test_cli_passes_proactive_options_to_scheduler(capsys, monkeypatch) -> None:
    captured_config = {}

    class FakeTick:
        def __init__(self, **kwargs):
            captured_config["config"] = kwargs["config"]

        def run_once(self):
            from drift_agent.proactive.types import ProactiveDecision

            return ProactiveDecision("skip")

    monkeypatch.setattr("drift_agent.cli.ProactiveAgentTick", FakeTick)

    exit_code = main(
        [
            "--mode",
            "stub",
            "--proactive-once",
            "--proactive-profile",
            "quiet",
            "--proactive-context",
            "custom-context.md",
            "--proactive-sources",
            "custom-sources.json",
        ]
    )

    config = captured_config["config"]
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert config.profile == "quiet"
    assert str(config.context_path) == "custom-context.md"
    assert str(config.sources_path) == "custom-sources.json"
