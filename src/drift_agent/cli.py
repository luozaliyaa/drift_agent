"""Command line entrypoint for the initial agent loop."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from collections.abc import Sequence

from drift_agent.config import load_deepseek_config, load_dotenv
from drift_agent.deepseek import DeepSeekPlanner
from drift_agent.drift import DriftConfig, DriftRunner
from drift_agent.loop import AgentLoop, StubPlanner
from drift_agent.memory import MemoryManager
from drift_agent.permissions import PermissionPolicy, prompt_approver
from drift_agent.proactive import ProactiveAgentTick, ProactiveConfig, ProactiveSourceLoader
from drift_agent.runtime import AsyncAgentRuntime
from drift_agent.runtime.input import AsyncInputReader
from drift_agent.runtime.renderer import TerminalRenderer
from drift_agent.runtime.scheduler import IdlePushScheduler
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
        "--allow-delete-without-ask-dir",
        action="append",
        default=[],
        help="Allow local file deletion under this workspace directory without prompting. Repeatable.",
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
        "--memory-optimizer-interval-seconds",
        type=int,
        default=64800,
        help="Seconds between automatic memory optimizer runs.",
    )
    parser.add_argument(
        "--memory-keep-count",
        type=int,
        default=8,
        help="Recent turns to keep out of full consolidation.",
    )
    parser.add_argument(
        "--memory-consolidation-min",
        type=int,
        default=None,
        help="Minimum eligible turns before memory consolidation runs.",
    )
    parser.add_argument(
        "--memory-optimize-now",
        action="store_true",
        help="Force a memory optimizer pass during this run.",
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
        help="Expose tools from a configured MCP server.",
    )
    parser.add_argument(
        "--mcp-config",
        default="mcp_servers.json",
        help="Path to MCP server configuration JSON.",
    )
    parser.add_argument(
        "--mcp-server",
        default="github",
        help="MCP server name to expose when MCP tools are enabled.",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List active model-callable tools and exit.",
    )
    parser.add_argument(
        "--proactive",
        choices=["on", "off"],
        default="off",
        help="Enable or disable terminal proactive notices in async REPL mode.",
    )
    parser.add_argument(
        "--proactive-profile",
        choices=["daily", "quiet", "dev_verify"],
        default="daily",
        help="Adaptive proactive tick profile.",
    )
    parser.add_argument(
        "--proactive-context",
        default="PROACTIVE_CONTEXT.md",
        help="Markdown rules file for proactive decisions.",
    )
    parser.add_argument(
        "--proactive-sources",
        default="proactive_sources.json",
        help="JSON source file for local proactive events.",
    )
    parser.add_argument(
        "--proactive-once",
        action="store_true",
        help="Run one proactive tick and exit when no task is provided.",
    )
    parser.add_argument(
        "--drift",
        choices=["on", "off"],
        default="on",
        help="Enable Drift background tasks when proactive has nothing to send.",
    )
    parser.add_argument(
        "--drift-dir",
        default="drift",
        help="Directory containing drift/skills and drift state.",
    )
    parser.add_argument(
        "--drift-min-interval-hours",
        type=float,
        default=1.0,
        help="Minimum hours between Drift runs.",
    )
    parser.add_argument(
        "--drift-max-steps",
        type=int,
        default=30,
        help="Maximum DeepSeek tool-loop steps for one Drift run.",
    )
    parser.add_argument(
        "--drift-permission-mode",
        choices=["deny", "allow"],
        default="deny",
        help="Permission mode for Drift background write/edit/shell tools.",
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
            allow_delete_without_ask_dirs=args.allow_delete_without_ask_dir,
        )
        memory_manager = None
        if args.memory == "on":
            memory_manager = MemoryManager(
                memory_dir=args.memory_dir,
                session_id=args.session,
                keep_count=args.memory_keep_count,
                consolidation_min=args.memory_consolidation_min,
                optimizer_interval_seconds=args.memory_optimizer_interval_seconds,
                optimize_now=args.memory_optimize_now,
            )
        registry = create_default_tool_registry(
            permission_policy=permission_policy,
            enable_web_tools=args.enable_web_tools,
            enable_mcp_tools=args.enable_mcp_tools,
            mcp_config_path=args.mcp_config,
            mcp_server=args.mcp_server,
            memory_manager=memory_manager,
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
    renderer = TerminalRenderer(trace=args.trace)
    scheduler = build_proactive_scheduler(args, stepper)
    runtime = AsyncAgentRuntime(
        stepper=stepper,
        max_steps=args.max_steps,
        scheduler=scheduler,
    )
    if args.proactive_once and not args.task:
        return await run_async_proactive_once(runtime, renderer)
    if not args.task:
        return await run_async_repl(args, runtime, renderer)
    return await run_async_task(args.task, runtime, renderer)


async def run_async_proactive_once(
    runtime: AsyncAgentRuntime,
    renderer: TerminalRenderer,
) -> int:
    if runtime.scheduler is None:
        return 0
    await runtime.scheduler.run_once()
    exit_code = 0
    while not runtime.events.empty():
        exit_code = renderer.render(await runtime.events.get())
    return exit_code


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
    if runtime.scheduler is not None and args.proactive == "on":
        await runtime.scheduler.start()
    reader = AsyncInputReader()
    exit_code = 0
    try:
        while True:
            render_pending_system_notices(runtime, renderer)
            notice_task = None
            if runtime.scheduler is not None and args.proactive == "on":
                notice_task = asyncio.create_task(
                    render_idle_system_notices(runtime, renderer)
                )
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
            finally:
                if notice_task is not None:
                    notice_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await notice_task

            if task.lower() in {"", "q", "quit", "exit"}:
                return exit_code

            try:
                exit_code = await run_async_task(task, runtime, renderer)
            except KeyboardInterrupt:
                await runtime.cancel_current()
                exit_code = await renderer.render_until_done(runtime.events)
            print()
    finally:
        if runtime.scheduler is not None:
            await runtime.scheduler.stop()
        render_pending_system_notices(runtime, renderer)


def build_stepper(args: argparse.Namespace, parser: argparse.ArgumentParser):
    if args.mode == "live":
        config = load_deepseek_config()
        try:
            permission_policy = PermissionPolicy(
                mode=args.permission_mode,
                approver=prompt_approver,
                allow_delete_without_ask_dirs=args.allow_delete_without_ask_dir,
            )
            memory_manager = None
            if args.memory == "on":
                memory_manager = MemoryManager(
                    memory_dir=args.memory_dir,
                    session_id=args.session,
                    keep_count=args.memory_keep_count,
                    consolidation_min=args.memory_consolidation_min,
                    optimizer_interval_seconds=args.memory_optimizer_interval_seconds,
                    optimize_now=args.memory_optimize_now,
                )
            tool_registry = create_default_tool_registry(
                permission_policy=permission_policy,
                enable_web_tools=args.enable_web_tools,
                enable_mcp_tools=args.enable_mcp_tools,
                mcp_config_path=args.mcp_config,
                mcp_server=args.mcp_server,
                memory_manager=memory_manager,
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


def build_proactive_scheduler(
    args: argparse.Namespace,
    stepper,
) -> IdlePushScheduler | None:
    if args.proactive != "on" and not args.proactive_once:
        return None
    config = ProactiveConfig(
        enabled=True,
        profile=args.proactive_profile,
        context_path=args.proactive_context,
        sources_path=args.proactive_sources,
    )
    tick = ProactiveAgentTick(
        config=config,
        client=getattr(stepper, "client", None),
        memory_manager=getattr(stepper, "memory_manager", None),
        source_loader=ProactiveSourceLoader(
            args.proactive_sources,
            mcp_config_path=args.mcp_config,
        ),
        drift_runner=build_drift_runner(args, stepper),
    )
    return IdlePushScheduler(
        runtime=None,
        tick=tick.run_once,
        profile=args.proactive_profile,
        enabled=True,
    )


def build_drift_runner(
    args: argparse.Namespace,
    stepper,
) -> DriftRunner | None:
    if args.drift != "on":
        return None
    client = getattr(stepper, "client", None)
    if client is None:
        return None
    return DriftRunner(
        config=DriftConfig(
            enabled=True,
            drift_dir=args.drift_dir,
            min_interval_hours=args.drift_min_interval_hours,
            max_steps=args.drift_max_steps,
            permission_mode=args.drift_permission_mode,
        ),
        client=client,
        memory_manager=getattr(stepper, "memory_manager", None),
    )


def render_pending_system_notices(
    runtime: AsyncAgentRuntime,
    renderer: TerminalRenderer,
) -> None:
    deferred = []
    while not runtime.events.empty():
        event = runtime.events.get_nowait()
        if event.type.value == "system_notice":
            renderer.render(event)
        else:
            deferred.append(event)
    for event in deferred:
        runtime.events.put_nowait(event)


async def render_idle_system_notices(
    runtime: AsyncAgentRuntime,
    renderer: TerminalRenderer,
) -> None:
    while True:
        event = await runtime.events.get()
        if event.type.value == "system_notice":
            renderer.render(event)
        else:
            runtime.events.put_nowait(event)
            await asyncio.sleep(0.05)


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
