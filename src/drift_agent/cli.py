"""Command line entrypoint for the initial agent loop."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from drift_agent.config import load_deepseek_config, load_dotenv
from drift_agent.deepseek import DeepSeekPlanner
from drift_agent.loop import AgentLoop, StubPlanner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the s01 drift agent loop.")
    parser.add_argument("task", help="Task or prompt for the agent loop.")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=3,
        help="Maximum loop iterations before stopping.",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "stub", "live"],
        default="auto",
        help="Use stub mode, live DeepSeek mode, or auto-detect from DEEPSEEK_API_KEY.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)

    config = load_deepseek_config()
    if args.mode == "live" or (args.mode == "auto" and config.is_configured):
        try:
            stepper = DeepSeekPlanner(config)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        stepper = StubPlanner()

    loop = AgentLoop(stepper=stepper, max_steps=args.max_steps)
    state = loop.run(args.task)

    print(f"status: {state.status.value}")
    if state.final_output:
        print(f"final: {state.final_output}")
    print("trace:")
    for event in state.events:
        print(f"- step {event.step}: {event.kind}: {event.message}")

    return 0 if state.status.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
