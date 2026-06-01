"""Synchronous stdio MCP client."""

from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, BinaryIO

from drift_agent.mcp.config import MCPServerConfig


class MCPClientError(RuntimeError):
    """Raised when an MCP server cannot be reached or returns an error."""


class SyncMCPClient:
    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.process: subprocess.Popen[bytes] | None = None
        self._next_id = 1

    def __enter__(self) -> "SyncMCPClient":
        self.start()
        self.initialize()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        if self.process is not None:
            return
        env = os.environ.copy()
        env.update(self.config.env)
        try:
            self.process = subprocess.Popen(
                [self.config.command, *self.config.args],
                cwd=str(self.config.cwd) if self.config.cwd else None,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise MCPClientError(f"Could not start MCP server {self.config.name}: {exc}") from exc

    def close(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()

    def initialize(self) -> dict[str, Any]:
        response = self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "drift-agent", "version": "0.1.0"},
            },
        )
        self.notify("notifications/initialized", {})
        return response

    def list_tools(self) -> list[dict[str, Any]]:
        result = self.request("tools/list", {})
        tools = result.get("tools", [])
        return tools if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        while True:
            message = self._read_with_timeout()
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise MCPClientError(format_mcp_error(message["error"]))
            result = message.get("result", {})
            return result if isinstance(result, dict) else {"result": result}

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _send(self, message: dict[str, Any]) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise MCPClientError("MCP server stdin is not available")
        payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
        process.stdin.write(header + payload)
        process.stdin.flush()

    def _read_with_timeout(self) -> dict[str, Any]:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._read_message)
            try:
                return future.result(timeout=self.config.timeout_seconds)
            except FutureTimeout as exc:
                self.close()
                raise MCPClientError(
                    f"MCP server {self.config.name} timed out after "
                    f"{self.config.timeout_seconds:g}s"
                ) from exc

    def _read_message(self) -> dict[str, Any]:
        process = self._require_process()
        if process.stdout is None:
            raise MCPClientError("MCP server stdout is not available")
        headers = read_headers(process.stdout)
        length = headers.get("content-length")
        if length is None:
            raise MCPClientError("MCP response missing Content-Length")
        try:
            content_length = int(length)
        except ValueError as exc:
            raise MCPClientError(f"Invalid MCP Content-Length: {length}") from exc
        payload = process.stdout.read(content_length)
        if len(payload) != content_length:
            raise MCPClientError("MCP server closed before sending a full message")
        try:
            message = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise MCPClientError(f"Invalid MCP JSON response: {exc}") from exc
        if not isinstance(message, dict):
            raise MCPClientError("MCP response must be a JSON object")
        return message

    def _require_process(self) -> subprocess.Popen[bytes]:
        if self.process is None:
            raise MCPClientError("MCP server is not running")
        return self.process


def read_headers(stream: BinaryIO) -> dict[str, str]:
    raw = bytearray()
    while not raw.endswith(b"\r\n\r\n"):
        chunk = stream.read(1)
        if not chunk:
            raise MCPClientError("MCP server closed while sending headers")
        raw.extend(chunk)
        if len(raw) > 8192:
            raise MCPClientError("MCP response headers are too large")
    headers: dict[str, str] = {}
    for line in raw.decode("ascii", errors="replace").split("\r\n"):
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return headers


def format_mcp_error(error: object) -> str:
    if isinstance(error, dict):
        message = error.get("message") or error.get("code") or error
        return f"MCP error: {message}"
    return f"MCP error: {error}"
