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

The CLI runs in `auto` mode by default: it uses DeepSeek when `DEEPSEEK_API_KEY` is configured and otherwise falls back to the deterministic stub.

## Future Extension Points

The step function is injectable, so later stages can replace the stub planner with model calls, tool execution, memory reads, or policy checks without rewriting the loop lifecycle.
