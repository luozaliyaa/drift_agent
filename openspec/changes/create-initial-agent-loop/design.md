# Design

## Overview

The `s01` agent loop is a deterministic orchestration shell. It owns task state, delegates each iteration to a step function, records events, and stops when a terminal status is reached or the configured step budget is exhausted.

## Components

- `AgentLoop`: runs the lifecycle and applies step results to state.
- `AgentState`: stores the task, current step count, status, events, and final output.
- `StepResult`: describes one iteration's action, observation, status update, and optional output.
- `AgentEvent`: records user-visible trace entries for CLI and tests.
- `StubPlanner`: provides deterministic behavior until future stages add real model/tool adapters.

## Behavior

The loop starts in `running` status and records a start event. Each iteration calls a step function with the current state. The returned `StepResult` is appended as an event and may update the loop status. If the step result leaves the loop running, the loop continues until `max_steps`; reaching that limit changes the status to `max_steps`.

Terminal statuses are `success`, `failure`, `halted`, and `max_steps`. Once terminal, the loop records a final event and returns the state.

## CLI

The CLI accepts a task string and optional `--max-steps`. It runs the loop and prints the final status, optional final output, and the event trace. This keeps local verification possible without adding a service or UI.

## DeepSeek Configuration

The first live model adapter uses the DeepSeek OpenAI-compatible chat endpoint. The default model is `deepseek-v4-pro` and the default base URL is `https://api.deepseek.com`. The API key is read from `DEEPSEEK_API_KEY`, optionally loaded from a local `.env` file.

The CLI runs live DeepSeek mode by default. The deterministic stub remains available only through `--mode stub` for offline tests.

## Tool Use

The `s02` tool-use layer follows the dispatch-map pattern from the reference implementation. Tools are defined separately from their handlers, then exposed to DeepSeek with OpenAI-compatible function schemas.

Supported tools are `bash`, `read_file`, `write_file`, `edit_file`, and `glob`. File tools are constrained to the current workspace with `safe_path`. Bash has a small dangerous-command blocklist and will be expanded with a permission layer in a later stage.

When DeepSeek returns `tool_calls`, the planner executes each tool in order, appends `role=tool` results to the conversation, and calls the model again until it returns a final answer or reaches the configured tool-round limit.

## Future Extension Points

The step function is injectable, so later stages can replace the stub planner with model calls, tool execution, memory reads, or policy checks without rewriting the loop lifecycle.
