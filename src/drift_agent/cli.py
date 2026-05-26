"""Command line entrypoint for the initial agent loop."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from drift_agent.config import load_deepseek_config, load_dotenv
from drift_agent.deepseek import DeepSeekPlanner
from drift_agent.loop import AgentLoop, StubPlanner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the s01 drift agent with DeepSeek.")
    parser.add_argument(
        "task",
        nargs="?",
        help="Task or prompt for the agent loop. Omit to start interactive mode.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=1,
        help="Maximum loop iterations before stopping.",
    )
    parser.add_argument(
        "--mode",
        choices=["live", "stub"],
        default="live",
        help="Use live DeepSeek mode by default; stub is only for local tests.",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Print the agent loop trace after the final answer.",
    )
    parser.add_argument(
        "--max-tool-rounds",
        type=int,
        default=8,
        help="Maximum model/tool exchange rounds before stopping.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_console_encoding()
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)

    stepper = build_stepper(args, parser)
    if not args.task:
        return run_repl(args, stepper)
    return run_task(args.task, args, stepper)


def build_stepper(args: argparse.Namespace, parser: argparse.ArgumentParser):
    if args.mode == "live":
        config = load_deepseek_config()
        try:
            return DeepSeekPlanner(config, max_tool_rounds=args.max_tool_rounds)
        except ValueError as exc:
            parser.error(str(exc))
    return StubPlanner()


def run_repl(args: argparse.Namespace, stepper) -> int:
    print("drift-agent interactive mode. Type q, exit, or an empty line to quit.")
    exit_code = 0
    while True:
        try:
            task = input("drift-agent> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return exit_code

        if task.lower() in {"", "q", "quit", "exit"}:
            return exit_code

        exit_code = run_task(task, args, stepper)
        print()


def run_task(task: str, args: argparse.Namespace, stepper) -> int:
    loop = AgentLoop(stepper=stepper, max_steps=args.max_steps)
    state = loop.run(task)

    print(f"status: {state.status.value}")
    if state.final_output:
        print(f"final: {state.final_output}")
    if args.trace:
        print("trace:")
        for event in state.events:
            print(f"- step {event.step}: {event.kind}: {event.message}")

    return 0 if state.status.is_success else 1


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
