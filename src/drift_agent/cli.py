"""Command line entrypoint for the initial agent loop."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from drift_agent.config import load_deepseek_config, load_dotenv
from drift_agent.deepseek import DeepSeekPlanner
from drift_agent.loop import AgentLoop, StubPlanner
from drift_agent.memory import MemoryManager
from drift_agent.permissions import PermissionPolicy, prompt_approver
from drift_agent.runtime import AsyncAgentRuntime
from drift_agent.runtime.input import AsyncInputReader
from drift_agent.runtime.renderer import TerminalRenderer
from drift_agent.tools import create_default_tool_registry


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
    parser.add_argument(
        "--permission-mode",
        choices=["ask", "allow", "deny"],
        default="ask",
        help="How to handle approval-required tool calls.",
    )
    parser.add_argument(
        "--memory",
        choices=["on", "off"],
        default="on",
        help="Enable or disable local Markdown and SQLite memory.",
    )
    parser.add_argument(
        "--session",
        default="default",
        help="Memory session name for SQLite context continuity.",
    )
    parser.add_argument(
        "--memory-dir",
        default=".memory",
        help="Directory for local memory files and SQLite context.",
    )
    parser.add_argument(
        "--show-memory",
        action="store_true",
        help="Print memory sources injected into the model prompt.",
    )
    parser.add_argument(
        "--runtime",
        choices=["async", "sync"],
        default="async",
        help="Use the async CLI runtime or the legacy sync path.",
    )
    parser.add_argument(
        "--enable-web-tools",
        action="store_true",
        help="Reserve web tool provider hooks. Real web tools are not implemented yet.",
    )
    parser.add_argument(
        "--enable-mcp-tools",
        action="store_true",
        help="Reserve MCP tool provider hooks. Real MCP tools are not implemented yet.",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List active model-callable tools and exit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_console_encoding()
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_tools:
        permission_policy = PermissionPolicy(
            mode=args.permission_mode,
            approver=prompt_approver,
        )
        registry = create_default_tool_registry(
            permission_policy=permission_policy,
            enable_web_tools=args.enable_web_tools,
            enable_mcp_tools=args.enable_mcp_tools,
        )
        for info in registry.list_tool_info():
            print(
                f"{info['id']}\t{info['encoded_name']}\t"
                f"{info['provider']}\t{info['description']}"
            )
        return 0

    stepper = build_stepper(args, parser)
    if args.runtime == "sync":
        if not args.task:
            return run_repl(args, stepper)
        return run_task(args.task, args, stepper)

    return asyncio.run(run_async_cli(args, stepper))


async def run_async_cli(args: argparse.Namespace, stepper) -> int:
    runtime = AsyncAgentRuntime(stepper=stepper, max_steps=args.max_steps)
    renderer = TerminalRenderer(trace=args.trace)
    if not args.task:
        return await run_async_repl(args, runtime, renderer)
    return await run_async_task(args.task, runtime, renderer)


async def run_async_task(
    task: str,
    runtime: AsyncAgentRuntime,
    renderer: TerminalRenderer,
) -> int:
    run = await runtime.submit(task)
    render = asyncio.create_task(renderer.render_until_done(runtime.events))
    try:
        await run
    except Exception:
        pass
    return await render


async def run_async_repl(
    args: argparse.Namespace,
    runtime: AsyncAgentRuntime,
    renderer: TerminalRenderer,
) -> int:
    print("drift-agent async interactive mode. Type q, exit, or an empty line to quit.")
    reader = AsyncInputReader()
    exit_code = 0
    while True:
        try:
            task = (await reader.read()).strip()
        except KeyboardInterrupt:
            if runtime.busy:
                await runtime.cancel_current()
                exit_code = await renderer.render_until_done(runtime.events)
                continue
            print()
            return exit_code
        except EOFError:
            print()
            return exit_code

        if task.lower() in {"", "q", "quit", "exit"}:
            return exit_code

        try:
            exit_code = await run_async_task(task, runtime, renderer)
        except KeyboardInterrupt:
            await runtime.cancel_current()
            exit_code = await renderer.render_until_done(runtime.events)
        print()


def build_stepper(args: argparse.Namespace, parser: argparse.ArgumentParser):
    if args.mode == "live":
        config = load_deepseek_config()
        try:
            permission_policy = PermissionPolicy(
                mode=args.permission_mode,
                approver=prompt_approver,
            )
            memory_manager = None
            if args.memory == "on":
                memory_manager = MemoryManager(
                    memory_dir=args.memory_dir,
                    session_id=args.session,
                )
            tool_registry = create_default_tool_registry(
                permission_policy=permission_policy,
                enable_web_tools=args.enable_web_tools,
                enable_mcp_tools=args.enable_mcp_tools,
            )
            return DeepSeekPlanner(
                config,
                max_tool_rounds=args.max_tool_rounds,
                permission_policy=permission_policy,
                memory_manager=memory_manager,
                show_memory=args.show_memory,
                tool_registry=tool_registry,
            )
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
