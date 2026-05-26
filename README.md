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

Model-facing function names are encoded with double underscores, for example
`workspace.read_file` is exposed as `workspace__read_file`.

List active tools:

```powershell
python -m drift_agent.cli --list-tools
```

The tool system is backed by a registry package under `src/drift_agent/tools/`.
Workspace tools are active by default. Web and MCP providers are reserved for
future expansion and are not exposed unless implemented.

Example:

```powershell
python -m drift_agent.cli "Read README.md and summarize this project" --trace
```

## Permissions

The live agent asks before running approval-required tools such as `write_file`,
`edit_file`, or potentially destructive shell commands.

```powershell
python -m drift_agent.cli "Create notes/plan.txt with a short plan"
```

For trusted experiments, bypass prompts:

```powershell
python -m drift_agent.cli "Create notes/plan.txt with a short plan" --permission-mode allow
```

To deny every approval-required operation:

```powershell
python -m drift_agent.cli "Try to edit README.md" --permission-mode deny
```

## Memory

Memory is enabled by default in live mode.

- `.memory/MEMORY.md`: Markdown memory index injected every turn
- `.memory/items/*.md`: long-term Markdown memories
- `.memory/context.sqlite3`: SQLite session context and tool-call history

Useful options:

```powershell
python -m drift_agent.cli "记住我喜欢用 tabs 缩进" --show-memory
python -m drift_agent.cli "继续刚才的任务" --session project-a
python -m drift_agent.cli "临时问答，不使用记忆" --memory off
python -m drift_agent.cli "使用自定义记忆目录" --memory-dir .my-memory
```

## Runtime Events

The async runtime emits internal events such as `user_message`, `agent_started`,
`agent_finished`, and `agent_failed`. Use `--trace` to show them in the terminal.

Future proactive push support will attach to the reserved scheduler interface and
emit non-blocking system notices while the agent is idle.
