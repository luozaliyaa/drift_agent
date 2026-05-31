from __future__ import annotations

import socket

from drift_agent.tools.web import WebToolProvider


class FakeHeaders:
    def __init__(self, content_type: str) -> None:
        self.content_type = content_type

    def get(self, name: str, default=None):
        if name.lower() == "content-type":
            return self.content_type
        return default


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        content_type: str = "text/html; charset=utf-8",
        url: str = "https://example.com/page",
    ) -> None:
        self.body = body
        self.headers = FakeHeaders(content_type)
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self.body
        return self.body[:size]

    def geturl(self) -> str:
        return self.url


def test_web_fetch_is_disabled_by_default() -> None:
    provider = WebToolProvider(enabled=False)

    result = provider.call_tool("web.fetch", {"url": "https://example.com"})

    assert result.error is True
    assert result.output == "Tool disabled: web.fetch"


def test_web_fetch_returns_clean_html_text(monkeypatch) -> None:
    captured = {}

    def fake_getaddrinfo(host, port, type=0):
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                0,
                "",
                ("93.184.216.34", port),
            )
        ]

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeResponse(
            b"<html><body><h1>Hello</h1><script>x()</script><p>World</p></body></html>"
        )

    monkeypatch.setattr("drift_agent.tools.web.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("drift_agent.tools.web.urlopen", fake_urlopen)
    provider = WebToolProvider(enabled=True)

    result = provider.call_tool(
        "web.fetch",
        {"url": "https://example.com/page", "timeout_seconds": 2},
    )

    assert result.error is False
    assert captured["url"] == "https://example.com/page"
    assert captured["timeout"] == 2.0
    assert "Fetched: https://example.com/page" in result.output
    assert "Hello" in result.output
    assert "World" in result.output
    assert "script" not in result.output


def test_web_fetch_blocks_private_addresses() -> None:
    provider = WebToolProvider(enabled=True)

    result = provider.call_tool("web.fetch", {"url": "http://127.0.0.1:8000"})

    assert result.error is True
    assert "Blocked non-public address" in result.output


def test_web_fetch_rejects_non_http_urls() -> None:
    provider = WebToolProvider(enabled=True)

    result = provider.call_tool("web.fetch", {"url": "file:///etc/passwd"})

    assert result.error is True
    assert "Only http and https URLs" in result.output
