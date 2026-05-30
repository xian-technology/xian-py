import asyncio
import inspect
import threading
from concurrent.futures import Future
from functools import wraps
from typing import Any, Generic, TypeVar

from xian_py.application_clients import (
    ContractClient,
    EventClient,
    StateKeyClient,
    TokenClient,
)
from xian_py.config import XianClientConfig
from xian_py.wallet import Wallet
from xian_py.xian_async import XianAsync

_T = TypeVar("_T")


class _SyncAsyncIterator(Generic[_T]):
    def __init__(self, owner: "Xian", async_iterator: Any):
        self._owner = owner
        self._async_iterator = async_iterator
        self._closed = False

    def __iter__(self) -> "_SyncAsyncIterator[_T]":
        return self

    def __next__(self) -> _T:
        if self._closed:
            raise StopIteration

        future = self._owner._schedule(self._async_iterator.__anext__())
        try:
            return future.result()
        except StopAsyncIteration as exc:
            self.close()
            raise StopIteration from exc

    def close(self) -> None:
        if self._closed:
            return
        self._owner._run_async(self._async_iterator.aclose())
        self._closed = True


class Xian:
    """Synchronous wrapper around a persistent XianAsync runtime."""

    def __init__(
        self,
        node_url: str,
        chain_id: str = None,
        wallet: Wallet = None,
        *,
        config: XianClientConfig | None = None,
    ):
        self.node_url = node_url
        self.wallet = wallet if wallet else Wallet()
        self._async_client = XianAsync(
            node_url,
            chain_id,
            self.wallet,
            config=config,
        )
        self._runtime_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

        if chain_id is None:
            self.chain_id = self.get_chain_id()
            self._async_client.chain_id = self.chain_id
            self._async_client._chain_id_set = True
        else:
            self.chain_id = chain_id

    def __enter__(self) -> "Xian":
        self._ensure_runtime()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __getattr__(self, name: str) -> Any:
        async_client = self.__dict__.get("_async_client")
        if async_client is None:
            raise AttributeError(f"{type(self).__name__!s} object has no attribute {name!r}")

        try:
            async_attr = getattr(async_client, name)
        except AttributeError as exc:
            raise AttributeError(
                f"{type(self).__name__!s} object has no attribute {name!r}"
            ) from exc

        if not callable(async_attr):
            return async_attr

        @wraps(async_attr)
        def _sync_delegate(*args: Any, **kwargs: Any) -> Any:
            return self._coerce_async_result(async_attr(*args, **kwargs))

        return _sync_delegate

    def _ensure_runtime(self) -> None:
        with self._runtime_lock:
            if self._loop is not None and self._thread is not None and self._thread.is_alive():
                return

            started = threading.Event()

            def _thread_main() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                started.set()
                loop.run_forever()
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.close()

            self._thread = threading.Thread(
                target=_thread_main,
                name="xian-py-sync-runtime",
                daemon=True,
            )
            self._thread.start()
            started.wait()

    def _schedule(self, coro: Any) -> Future:
        self._ensure_runtime()
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _run_async(self, coro: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self._schedule(coro).result()

        if hasattr(coro, "close"):
            coro.close()
        raise RuntimeError(
            "Cannot call sync methods from within an async context. "
            "Use XianAsync directly for async operations."
        )

    def _coerce_async_result(self, result: Any) -> Any:
        if inspect.isasyncgen(result):
            return _SyncAsyncIterator(self, result)
        if inspect.isawaitable(result):
            return self._run_async(result)
        return result

    def close(self) -> None:
        with self._runtime_lock:
            loop = self._loop
            thread = self._thread
            if loop is None or thread is None:
                return

            asyncio.run_coroutine_threadsafe(
                self._async_client.close(),
                loop,
            ).result()
            loop.call_soon_threadsafe(loop.stop)
            thread.join()
            self._loop = None
            self._thread = None

    def contract(self, name: str) -> ContractClient:
        return ContractClient(self, name)

    def token(self, name: str = "currency") -> TokenClient:
        return TokenClient(self, name)

    def events(self, contract: str, event: str) -> EventClient:
        return EventClient(self, contract, event)

    def state_key(
        self,
        contract: str,
        variable: str,
        *keys: str,
    ) -> StateKeyClient:
        return StateKeyClient(self, contract, variable, tuple(keys))


def _make_sync_delegate(name: str, async_method: Any):
    @wraps(async_method)
    def _sync_delegate(self: Xian, *args: Any, **kwargs: Any) -> Any:
        async_attr = getattr(self._async_client, name)
        return self._coerce_async_result(async_attr(*args, **kwargs))

    return _sync_delegate


def _install_async_delegates() -> None:
    for name, async_method in inspect.getmembers(XianAsync):
        if name.startswith("_") or name == "close" or name in Xian.__dict__:
            continue
        if inspect.iscoroutinefunction(async_method) or inspect.isasyncgenfunction(async_method):
            setattr(Xian, name, _make_sync_delegate(name, async_method))


_install_async_delegates()
