"""Streaming result handlers for async adapters."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional
from datetime import datetime, timezone


@dataclass
class StreamingResult:
    """Accumulates streaming chunks into final result."""
    chunks: list[str] = field(default_factory=list)
    total_tokens: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    def add_chunk(self, chunk: str):
        """Add a chunk to the accumulator."""
        self.chunks.append(chunk)

    def get_content(self) -> str:
        """Get accumulated content."""
        return "".join(self.chunks)

    def complete(self, tokens: int = 0):
        """Mark streaming as complete."""
        self.completed_at = datetime.now(timezone.utc)
        self.total_tokens = tokens

    @property
    def duration_seconds(self) -> float:
        """Get duration in seconds."""
        end = self.completed_at or datetime.now(timezone.utc)
        return (end - self.started_at).total_seconds()


async def collect_stream(stream: AsyncIterator[str], timeout: float = 300) -> StreamingResult:
    """Collect all chunks from an async stream into a StreamingResult.

    Args:
        stream: Async iterator yielding string chunks
        timeout: Maximum time to wait for stream completion

    Returns:
        StreamingResult with all accumulated chunks

    Raises:
        asyncio.TimeoutError: If stream doesn't complete within timeout
        asyncio.CancelledError: If collection is cancelled (re-raised after cleanup)
    """
    result = StreamingResult()
    try:
        async with asyncio.timeout(timeout):
            async for chunk in stream:
                result.add_chunk(chunk)
    except asyncio.CancelledError:
        # Save partial results before re-raising
        result.complete()
        raise

    result.complete()
    return result
