# drift-agent

Minimal command line agent backed by the DeepSeek chat API.

## Configure

Create a local `.env` file in the project root:

```env
DEEPSEEK_API_KEY=sk-your-key-here
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

`.env` and `.memory/` are ignored by git.

## Run

From the project root:

```powershell
python -m drift_agent.cli "帮我写一个简单计划"
```

Or start interactive mode:

```powershell
python -m drift_agent.cli
```

The CLI uses live DeepSeek mode by default. For local offline tests only:

```powershell
python -m drift_agent.cli "write tests" --mode stub --trace
```

The default CLI runtime is async. The existing synchronous path is still
available as a fallback:

```powershell
python -m drift_agent.cli "write tests" --mode stub --runtime sync
```

The async runtime currently wraps the stable synchronous agent core with
`asyncio.to_thread()`. It provides the event-loop structure for future streaming,
cancellation, and proactive notices, while keeping model/tool/memory behavior
unchanged.

## Tools

Live mode exposes these workspace tools to the model:

- `workspace.bash`: run a shell command in the workspace
- `workspace.read_file`: read a workspace text file
- `workspace.write_file`: write text to a workspace file
- `workspace.edit_file`: replace exact text once
- `workspace.glob`: find files by glob pattern
- `workspace.list_dir`: list directory entries
- `workspace.file_info`: inspect file metadata
- `workspace.search_text`: search text in workspace files
- `workspace.make_dir`: create a workspace directory
- `workspace.move_file`: move or rename a workspace file
- `workspace.delete_file`: delete a workspace file

Model-facing function names are encoded with double underscores, for example
`workspace.read_file` is exposed as `workspace__read_file`.

List active tools:

```powershell
python -m drift_agent.cli --list-tools
```

The tool system is backed by a registry package under `src/drift_agent/tools/`.
Workspace tools are active by default. Web tools are opt-in. MCP tools are
available when a server is configured.

Example `mcp_servers.json` for GitHub:

```json
{
  "servers": {
    "github": {
      "command": "github-mcp-server",
      "args": ["stdio"],
      "env": {
        "GITHUB_TOKEN": "ghp_your_token"
      }
    }
  }
}
```

Expose GitHub MCP tools to the model:

```powershell
python -m drift_agent.cli --list-tools --enable-mcp-tools --mcp-server github --mcp-config mcp_servers.json
python -m drift_agent.cli "Check my GitHub notifications" --enable-mcp-tools --mcp-server github
```

Example:

```powershell
python -m drift_agent.cli "Read README.md and summarize this project" --trace
```

## Permissions

The live agent asks before running local file deletion operations. Normal reads,
web/API calls, output redirects, writes, edits, directory creation, and moves do
not prompt by default. Hard-denied shell commands such as `sudo shutdown now`
are still blocked.

```powershell
python -m drift_agent.cli "Create notes/plan.txt with a short plan"
```

For trusted experiments, bypass prompts:

```powershell
python -m drift_agent.cli "Create notes/plan.txt with a short plan" --permission-mode allow
```

To deny every approval-required deletion:

```powershell
python -m drift_agent.cli "Delete notes/old.txt" --permission-mode deny
```

To allow deletion under a specific workspace directory without prompting:

```powershell
python -m drift_agent.cli --allow-delete-without-ask-dir .pytest-tmp
```

The flag is repeatable. Only paths under the configured directories are allowed
without confirmation; other local deletion commands still prompt in `ask` mode.

## Memory

Memory is enabled by default in live mode.

- `.memory/SELF.md`: compact agent self model injected every turn
- `.memory/MEMORY.md`: compact long-term memory injected every turn
- `.memory/RECENT_CONTEXT.md`: compressed recent context plus recent turn window
- `.memory/HISTORY.md`: append-only timeline written by consolidation
- `.memory/PENDING.md`: pending facts waiting for optimizer archival
- `.memory/journal/YYYY-MM-DD.md`: daily history mirror
- `.memory/context.sqlite3`: SQLite session context and consolidation metadata
- `.memory/memory2.sqlite3`: local semantic memory records and embeddings

Live mode uses DeepSeek for consolidation and optimization. Test/stub mode can
still use the conservative local extraction fallback.

Useful options:

```powershell
python -m drift_agent.cli "记住我喜欢用 tabs 缩进" --show-memory
python -m drift_agent.cli "继续刚才的任务" --session project-a
python -m drift_agent.cli "临时问答，不使用记忆" --memory off
python -m drift_agent.cli "使用自定义记忆目录" --memory-dir .my-memory
python -m drift_agent.cli "optimize memory now" --memory-optimize-now
python -m drift_agent.cli "short consolidation window" --memory-keep-count 4 --memory-consolidation-min 2
```

When memory is enabled, live mode also exposes `memory.remember`,
`memory.recall`, and `memory.forget` as model-callable tools.

## Plugins

Plugins are enabled by default and are loaded from `plugins/*/plugin.py`.

Useful options:

```powershell
python -m drift_agent.cli "Check the repo" --plugins-dir plugins
python -m drift_agent.cli "Run without plugins" --plugins off
```

Minimal prompt plugin:

```python
from drift_agent.plugins import Plugin


class AgentFocusPlugin(Plugin):
    name = "agent_focus"

    def prompt_sections(self):
        return [
            "User interest: prioritize AI Agent projects, GitHub activity, and tooling."
        ]
```

Minimal tool plugin:

```python
from drift_agent.plugins import Plugin
from drift_agent.tools.base import ToolCallResult, ToolSpec


class EchoPlugin(Plugin):
    name = "echo"

    def tools(self):
        return [
            ToolSpec(
                canonical_id="plugin.echo",
                aliases=("echo_plugin",),
                description="Echo text from a plugin.",
                parameters={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            )
        ]

    def call_tool(self, canonical_id, arguments):
        return ToolCallResult(canonical_id, "echo: " + str(arguments["text"]))
```

Tool hooks can deny, replace, or rewrite calls:

```python
from drift_agent.plugins import Plugin, ToolHookResult


class SafetyPlugin(Plugin):
    name = "safety"

    def before_tool_call(self, context):
        if context.canonical_id == "workspace.bash" and "vim " in context.arguments.get("command", ""):
            return ToolHookResult.deny("Interactive editors are not allowed.")
        return None
```

Plugins can also provide proactive sources:

```python
class GitHubWatchPlugin(Plugin):
    name = "github_watch"

    def proactive_sources(self):
        return [
            {
                "type": "github_mcp",
                "channel": "content",
                "server": "github",
                "tool": "list_notifications",
                "arguments": {"filter": "participating"},
            }
        ]
```

## Runtime Events

The async runtime emits internal events such as `user_message`, `agent_started`,
`agent_finished`, and `agent_failed`. Use `--trace` to show them in the terminal.

## Proactive Notices

Proactive notices are opt-in. In the first implementation they are terminal
`system_notice` events only; Telegram/MCP ACK delivery is reserved for a later
phase.

Run one proactive tick and exit:

```powershell
python -m drift_agent.cli --mode stub --proactive-once
```

### Drift Background Tasks

When proactive is enabled and no alert/content/context item is visible, Drift can
use idle time to run one background skill from `drift/skills/*/SKILL.md`.

Drift is enabled by default whenever proactive is enabled. It records successful
runs in `drift/drift.json`, keeps a shared `drift/drift_note.md`, and creates
per-skill `state.json` files. Drift can send at most one terminal notice per run
with `message_push`, and every run must finish with `finish_drift`.

Useful options:

```powershell
python -m drift_agent.cli --proactive on --drift on
python -m drift_agent.cli --proactive on --drift off
python -m drift_agent.cli --proactive on --drift-dir drift --drift-min-interval-hours 1
python -m drift_agent.cli --proactive on --drift-permission-mode allow
```

Minimal skill:

```markdown
---
name: explore-curiosity
description: Ask one light question when there is nothing else to push
---

## Goal
Ask one small, natural question if the queue has anything useful.

## Workflow
1. Read `drift/skills/explore-curiosity/queue.md`.
2. If the queue has a question, call `message_push` once.
3. Update queue/state files under `drift/`.
4. Call `finish_drift` with `message_result="sent"` or `"silent"`.
```

Enable idle proactive notices in async interactive mode:

```powershell
python -m drift_agent.cli --proactive on --proactive-profile daily
```

Useful files:

- `PROACTIVE_CONTEXT.md`: user-maintained rules for what is worth pushing
- `proactive_sources.json`: local static/file proactive sources

Example `proactive_sources.json`:

```json
{
  "sources": [
    {
      "type": "static",
      "channel": "alert",
      "name": "local",
      "events": [
        {
          "event_id": "demo-alert",
          "title": "Build finished",
          "content": "The local build finished successfully."
        }
      ]
    }
  ]
}
```

GitHub MCP proactive source:

```json
{
  "sources": [
    {
      "type": "github_mcp",
      "channel": "content",
      "name": "github",
      "server": "github",
      "tool": "list_notifications",
      "arguments": {
        "filter": "participating"
      }
    }
  ]
}
```

GitHub MCP results are normalized into alert/content/context events. Mentions,
review requests, assignments, and failed checks are promoted to `alert`; other
items use the configured source channel.
