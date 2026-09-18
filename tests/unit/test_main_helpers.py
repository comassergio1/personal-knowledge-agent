"""Boot-retry helper: the app survives a still-booting qdrant at daemon start."""

from __future__ import annotations

import pytest

from app.main import _ensure_collections_ready


class _FlakyStore:
    """Fails ``ensure_collection`` a fixed number of times, then works."""

    def __init__(self, *, failures_before_success: int) -> None:
        self.failures_before_success = failures_before_success
        self.calls = 0

    async def ensure_collection(self, size: int) -> None:
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise ConnectionError("qdrant not ready")


class _NeverReadyStore:
    async def ensure_collection(self, size: int) -> None:
        raise ConnectionError("qdrant not ready")


@pytest.mark.asyncio
async def test_retries_until_qdrant_ready() -> None:
    vector = _FlakyStore(failures_before_success=3)
    memory = _FlakyStore(failures_before_success=0)
    await _ensure_collections_ready(vector, memory, size=768)
    assert vector.calls == 4
    assert memory.calls == 1


@pytest.mark.asyncio
async def test_always_failing_raises() -> None:
    never = _NeverReadyStore()
    with pytest.raises(RuntimeError, match="qdrant did not become ready"):
        await _ensure_collections_ready(never, never, size=768)