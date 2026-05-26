"""Async input helpers."""

from __future__ import annotations

import asyncio


class AsyncInputReader:
    def __init__(self, prompt: str = "drift-agent> ") -> None:
        self.prompt = prompt

    async def read(self) -> str:
        return await asyncio.to_thread(input, self.prompt)
