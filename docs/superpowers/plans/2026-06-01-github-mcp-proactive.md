# GitHub MCP Proactive Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Drift Agent read GitHub content through an MCP server and turn it into proactive terminal notices.

**Architecture:** Add a small stdlib MCP stdio client/config layer, wire it into the existing `MCPToolProvider`, and extend proactive sources with a `github_mcp` source type. The proactive source normalizes MCP tool results into existing `ProactiveEvent` objects, so the current DeepSeek decision loop and terminal delivery remain unchanged.

**Tech Stack:** Python 3.11, stdlib subprocess/json/threading, pytest.

---

### Task 1: MCP Config And Client

**Files:**
- Create: `src/drift_agent/mcp/__init__.py`
- Create: `src/drift_agent/mcp/config.py`
- Create: `src/drift_agent/mcp/client.py`
- Test: `tests/test_mcp_config.py`

- [ ] **Step 1: Parse `mcp_servers.json`**

Support both object and list forms:

```json
{"servers":{"github":{"command":"github-mcp-server","args":["stdio"],"env":{"GITHUB_TOKEN":"..."}}}}
```

- [ ] **Step 2: Implement a sync stdio MCP client**

Implement initialize, tools/list, and tools/call over Content-Length framed JSON-RPC.

### Task 2: MCP Tool Provider

**Files:**
- Modify: `src/drift_agent/tools/mcp.py`
- Modify: `src/drift_agent/tools/registry.py`
- Modify: `src/drift_agent/cli.py`
- Test: `tests/test_tool_registry.py`

- [ ] **Step 1: Expose MCP tools when enabled**

When `--enable-mcp-tools --mcp-server github --mcp-config mcp_servers.json` is used, list MCP server tools as `mcp.github.<tool>`.

- [ ] **Step 2: Dispatch MCP calls**

Call the configured MCP server tool and return compact JSON output.

### Task 3: GitHub MCP Proactive Source

**Files:**
- Modify: `src/drift_agent/proactive/types.py`
- Modify: `src/drift_agent/proactive/sources.py`
- Modify: `src/drift_agent/cli.py`
- Test: `tests/test_proactive_sources.py`

- [ ] **Step 1: Add source fields**

Add `server`, `tool`, and `arguments` to `ProactiveSource`.

- [ ] **Step 2: Add `github_mcp` source type**

Call the MCP tool and normalize returned notifications/issues/PRs into `ProactiveEvent`.

- [ ] **Step 3: Keep failure isolated**

Missing config, missing server, tool errors, and malformed payloads return no events instead of breaking other sources.

### Task 4: Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document config examples**

Show `mcp_servers.json` and `proactive_sources.json` examples for GitHub.

- [ ] **Step 2: Run tests**

```powershell
& 'C:\Users\86158\AppData\Local\Programs\Python\Python311\python.exe' -m pytest
git diff --check
```
