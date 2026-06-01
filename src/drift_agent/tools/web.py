"""Web tools provider."""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from drift_agent.tools.base import ToolCallResult, ToolProvider, ToolSpec, truncate_output

DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_FETCH_BYTES = 1_000_000
MAX_TEXT_CHARS = 20_000


class WebToolProvider(ToolProvider):
    namespace = "web"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self._specs = [
            ToolSpec(
                canonical_id="web.search",
                provider=self.namespace,
                description="Search the web. Reserved for a future search provider.",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                enabled=False,
                risk="network",
                category="web",
                search_hint="Search the public web.",
            ),
            ToolSpec(
                canonical_id="web.fetch",
                provider=self.namespace,
                aliases=("web_fetch",),
                description=(
                    "Fetch an HTTP or HTTPS URL and return readable text. "
                    "Private, local, and non-web URLs are blocked."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "max_chars": {
                            "type": "integer",
                            "description": "Maximum returned characters, up to 20000.",
                        },
                        "timeout_seconds": {
                            "type": "number",
                            "description": "Network timeout, up to 30 seconds.",
                        },
                    },
                    "required": ["url"],
                },
                enabled=enabled,
                risk="network",
                category="web",
                search_hint="Fetch public HTTP or HTTPS URL contents.",
            ),
        ]

    def list_tools(self) -> list[ToolSpec]:
        return self._specs

    def call_tool(self, canonical_id: str, arguments: dict[str, Any]) -> ToolCallResult:
        if canonical_id != "web.fetch" or not self.enabled:
            return ToolCallResult(canonical_id, f"Tool disabled: {canonical_id}", True)
        try:
            output = self.fetch(
                url=str(arguments.get("url", "")),
                max_chars=_bounded_int(arguments.get("max_chars"), MAX_TEXT_CHARS),
                timeout_seconds=_bounded_float(
                    arguments.get("timeout_seconds"),
                    DEFAULT_TIMEOUT_SECONDS,
                    upper=30.0,
                ),
            )
        except Exception as exc:
            return ToolCallResult(canonical_id, f"Error: {exc}", True)
        return ToolCallResult(canonical_id, truncate_output(output))

    def fetch(
        self,
        url: str,
        max_chars: int = MAX_TEXT_CHARS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> str:
        safe_url = _validate_public_url(url)
        request = Request(
            safe_url,
            headers={
                "User-Agent": "drift-agent/0.1 (+https://local)",
                "Accept": "text/html,application/xhtml+xml,application/json,"
                "application/xml,text/plain,*/*;q=0.8",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                content_type = response.headers.get("content-type", "")
                if not _is_textual_content(content_type):
                    return f"Error: Unsupported content type: {content_type or 'unknown'}"
                raw = response.read(MAX_FETCH_BYTES + 1)
                truncated = len(raw) > MAX_FETCH_BYTES
                raw = raw[:MAX_FETCH_BYTES]
                final_url = response.geturl()
        except HTTPError as exc:
            return f"Error: HTTP {exc.code}: {exc.reason}"
        except URLError as exc:
            return f"Error: {exc.reason}"

        charset = _charset_from_content_type(content_type) or "utf-8"
        text = raw.decode(charset, errors="replace")
        if _looks_like_html(content_type, text):
            text = _html_to_text(text)
        else:
            text = _clean_text(text)

        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "\n... (truncated)"
        if truncated:
            text += "\n... (response truncated at 1000000 bytes)"

        title = f"Fetched: {final_url}"
        if content_type:
            title += f"\nContent-Type: {content_type}"
        return title + "\n\n" + (text or "(empty response)")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag in {"p", "div", "section", "article", "br", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag in {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def _validate_public_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are supported")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed")

    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("Localhost URLs are not allowed")
    _validate_public_host(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    return parsed.geturl()


def _validate_public_host(host: str, port: int) -> None:
    try:
        _validate_public_ip(ipaddress.ip_address(host))
        return
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(f"Could not resolve host: {host}") from exc
    if not infos:
        raise ValueError(f"Could not resolve host: {host}")
    for info in infos:
        address = info[4][0]
        _validate_public_ip(ipaddress.ip_address(address))


def _validate_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ValueError(f"Blocked non-public address: {address}")


def _is_textual_content(content_type: str) -> bool:
    if not content_type:
        return True
    media_type = content_type.split(";", 1)[0].strip().lower()
    return (
        media_type.startswith("text/")
        or media_type in {"application/json", "application/xml", "application/xhtml+xml"}
        or media_type.endswith("+json")
        or media_type.endswith("+xml")
    )


def _charset_from_content_type(content_type: str) -> str | None:
    match = re.search(r"charset=([^\s;]+)", content_type, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip("\"'")


def _looks_like_html(content_type: str, text: str) -> bool:
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type in {"text/html", "application/xhtml+xml"} or bool(
        re.search(r"<\s*html|<\s*body|<\s*p[\s>]", text, re.IGNORECASE)
    )


def _html_to_text(source: str) -> str:
    parser = _TextExtractor()
    parser.feed(source)
    parser.close()
    return _clean_text(html.unescape(" ".join(parser.parts)))


def _clean_text(text: str) -> str:
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned = re.sub(r"[ \t]+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def _bounded_int(value: object, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(parsed, MAX_TEXT_CHARS))


def _bounded_float(value: object, default: float, upper: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(1.0, min(parsed, upper))
