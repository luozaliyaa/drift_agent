# drift-agent

Minimal command line agent backed by the DeepSeek chat API.

## Configure

Create a local `.env` file in the project root:

```env
DEEPSEEK_API_KEY=sk-your-key-here
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

`.env` is ignored by git.

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

## Tools

Live mode exposes these workspace tools to the model:

- `bash`: run a shell command in the workspace
- `read_file`: read a workspace text file
- `write_file`: write text to a workspace file
- `edit_file`: replace exact text once
- `glob`: find files by glob pattern

Example:

```powershell
python -m drift_agent.cli "Read README.md and summarize this project" --trace
```
