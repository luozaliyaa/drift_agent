# Create Initial Agent Loop (s01)

## What

Create the first runnable Python agent loop skeleton for the project. The loop accepts a task, runs deterministic iterations, records step events, and terminates with a clear final status.

## Why

The repository needs a small foundation before adding model calls, tools, memory, or UI layers. A deterministic loop gives future work a stable orchestration boundary and makes the earliest milestone easy to test.

## Scope

- Add a Python package for the initial agent loop.
- Add typed loop state, step result, status, and event structures.
- Add a CLI entrypoint for smoke testing.
- Add unit tests for initialization and termination behavior.

## Non-goals

- Real LLM provider integration.
- Tool registry or tool execution.
- Persistent memory or storage.
- Streaming, concurrency, or UI workflows.
