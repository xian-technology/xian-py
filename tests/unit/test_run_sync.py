import asyncio

import pytest

from xian_py.run_sync import run_sync


async def _add(a: int, b: int) -> int:
    await asyncio.sleep(0)
    return a + b


def test_run_sync_runs_awaitable_without_existing_loop() -> None:
    assert run_sync(_add(2, 3)) == 5


def test_run_sync_raises_when_called_inside_running_loop() -> None:
    async def invoke() -> None:
        awaitable = _add(1, 1)
        try:
            with pytest.raises(RuntimeError):
                run_sync(awaitable)
        finally:
            awaitable.close()

    asyncio.run(invoke())


def test_run_sync_can_use_background_thread_inside_running_loop() -> None:
    async def invoke() -> int:
        return run_sync(_add(4, 6), allow_thread=True)

    assert asyncio.run(invoke()) == 10


def test_run_sync_reraises_background_thread_exception() -> None:
    async def fail() -> None:
        await asyncio.sleep(0)
        raise ValueError("boom")

    async def invoke() -> None:
        with pytest.raises(ValueError, match="boom"):
            run_sync(fail(), allow_thread=True)

    asyncio.run(invoke())
