import asyncio
import threading
from concurrent.futures import Future
from typing import Any, Generic, TypeVar

from xian_py.application_clients import (
    ContractClient,
    EventClient,
    StateKeyClient,
    TokenClient,
)
from xian_py.config import XianClientConfig
from xian_py.models import (
    BdsStatus,
    DeveloperRewardSummary,
    IndexedBlock,
    IndexedEvent,
    IndexedTransaction,
    LiveEvent,
    NodeStatus,
    PerformanceStatus,
    StateEntry,
    TransactionReceipt,
    TransactionSubmission,
)
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

    def _ensure_runtime(self) -> None:
        with self._runtime_lock:
            if (
                self._loop is not None
                and self._thread is not None
                and self._thread.is_alive()
            ):
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
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
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

    def get_tx(self, tx_hash: str) -> TransactionReceipt:
        return self._run_async(self._async_client.get_tx(tx_hash))

    def get_balance(
        self,
        address: str = None,
        contract: str = "currency",
    ) -> int | float:
        return self._run_async(
            self._async_client.get_balance(address, contract)
        )

    def send_tx(
        self,
        contract: str,
        function: str,
        kwargs: dict,
        stamps: int | None = None,
        nonce: int = None,
        chain_id: str = None,
        mode: str | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        stamp_margin: float | None = None,
        min_stamp_headroom: int | None = None,
    ) -> TransactionSubmission:
        return self._run_async(
            self._async_client.send_tx(
                contract=contract,
                function=function,
                kwargs=kwargs,
                stamps=stamps,
                nonce=nonce,
                chain_id=chain_id,
                mode=mode,
                wait_for_tx=wait_for_tx,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                stamp_margin=stamp_margin,
                min_stamp_headroom=min_stamp_headroom,
            )
        )

    def send(
        self,
        amount: int | float | str,
        to_address: str,
        token: str = "currency",
        stamps: int | None = None,
        mode: str | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        stamp_margin: float | None = None,
        min_stamp_headroom: int | None = None,
    ) -> TransactionSubmission:
        return self._run_async(
            self._async_client.send(
                amount,
                to_address,
                token,
                stamps=stamps,
                mode=mode,
                wait_for_tx=wait_for_tx,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                stamp_margin=stamp_margin,
                min_stamp_headroom=min_stamp_headroom,
            )
        )

    def simulate(self, contract: str, function: str, kwargs: dict) -> dict:
        return self._run_async(
            self._async_client.simulate(contract, function, kwargs)
        )

    def call(self, contract: str, function: str, kwargs: dict) -> Any:
        return self._run_async(
            self._async_client.call(contract, function, kwargs)
        )

    def estimate_stamps(
        self,
        contract: str,
        function: str,
        kwargs: dict,
        *,
        stamp_margin: float | None = None,
        min_stamp_headroom: int | None = None,
    ) -> dict:
        return self._run_async(
            self._async_client.estimate_stamps(
                contract,
                function,
                kwargs,
                stamp_margin=stamp_margin,
                min_stamp_headroom=min_stamp_headroom,
            )
        )

    def get_state(
        self,
        contract: str,
        variable: str,
        *keys: object,
    ) -> None | int | float | dict | str:
        return self._run_async(
            self._async_client.get_state(contract, variable, *keys)
        )

    def get_contract(self, contract: str) -> None | str:
        return self._run_async(self._async_client.get_contract(contract))

    def get_contract_code(self, contract: str) -> None | str:
        return self._run_async(self._async_client.get_contract_code(contract))

    def get_approved_amount(
        self,
        contract: str,
        address: str = None,
        token: str = "currency",
    ) -> int | float:
        return self._run_async(
            self._async_client.get_approved_amount(contract, address, token)
        )

    def approve(
        self,
        contract: str,
        token: str = "currency",
        amount: int | float | str = 999999999999,
        stamps: int | None = None,
        mode: str | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        stamp_margin: float | None = None,
        min_stamp_headroom: int | None = None,
    ) -> TransactionSubmission:
        return self._run_async(
            self._async_client.approve(
                contract,
                token,
                amount,
                stamps=stamps,
                mode=mode,
                wait_for_tx=wait_for_tx,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                stamp_margin=stamp_margin,
                min_stamp_headroom=min_stamp_headroom,
            )
        )

    def submit_contract(
        self,
        name: str,
        code: str,
        args: dict = None,
        stamps: int | None = None,
        mode: str | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        stamp_margin: float | None = None,
        min_stamp_headroom: int | None = None,
    ) -> TransactionSubmission:
        return self._run_async(
            self._async_client.submit_contract(
                name,
                code,
                args,
                stamps=stamps,
                mode=mode,
                wait_for_tx=wait_for_tx,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                stamp_margin=stamp_margin,
                min_stamp_headroom=min_stamp_headroom,
            )
        )

    def wait_for_tx(
        self,
        tx_hash: str,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ) -> TransactionReceipt:
        return self._run_async(
            self._async_client.wait_for_tx(
                tx_hash,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
        )

    def refresh_nonce(self) -> int:
        return self._run_async(self._async_client.refresh_nonce())

    def get_nodes(self) -> list:
        return self._run_async(self._async_client.get_nodes())

    def get_genesis(self):
        return self._run_async(self._async_client.get_genesis())

    def get_chain_id(self):
        return self._run_async(self._async_client.get_chain_id())

    def get_node_status(self) -> NodeStatus:
        return self._run_async(self._async_client.get_node_status())

    def get_perf_status(self) -> PerformanceStatus:
        return self._run_async(self._async_client.get_perf_status())

    def get_bds_status(self) -> BdsStatus:
        return self._run_async(self._async_client.get_bds_status())

    def get_developer_rewards(
        self, recipient_key: str
    ) -> DeveloperRewardSummary:
        return self._run_async(
            self._async_client.get_developer_rewards(recipient_key)
        )

    def list_blocks(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IndexedBlock]:
        return self._run_async(
            self._async_client.list_blocks(limit=limit, offset=offset)
        )

    def get_block(self, height: int) -> IndexedBlock | None:
        return self._run_async(self._async_client.get_block(height))

    def get_block_by_hash(self, block_hash: str) -> IndexedBlock | None:
        return self._run_async(self._async_client.get_block_by_hash(block_hash))

    def get_indexed_tx(self, tx_hash: str) -> IndexedTransaction | None:
        return self._run_async(self._async_client.get_indexed_tx(tx_hash))

    def list_txs_for_block(
        self,
        block_ref: str | int,
    ) -> list[IndexedTransaction]:
        return self._run_async(self._async_client.list_txs_for_block(block_ref))

    def list_txs_by_sender(
        self,
        sender: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IndexedTransaction]:
        return self._run_async(
            self._async_client.list_txs_by_sender(
                sender,
                limit=limit,
                offset=offset,
            )
        )

    def list_txs_by_contract(
        self,
        contract: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IndexedTransaction]:
        return self._run_async(
            self._async_client.list_txs_by_contract(
                contract,
                limit=limit,
                offset=offset,
            )
        )

    def get_events_for_tx(self, tx_hash: str) -> list[IndexedEvent]:
        return self._run_async(self._async_client.get_events_for_tx(tx_hash))

    def list_events(
        self,
        contract: str,
        event: str,
        *,
        limit: int = 100,
        offset: int = 0,
        after_id: int | None = None,
    ) -> list[IndexedEvent]:
        return self._run_async(
            self._async_client.list_events(
                contract,
                event,
                limit=limit,
                offset=offset,
                after_id=after_id,
            )
        )

    def get_state_history(
        self,
        key: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StateEntry]:
        return self._run_async(
            self._async_client.get_state_history(
                key,
                limit=limit,
                offset=offset,
            )
        )

    def get_state_for_tx(self, tx_hash: str) -> list[StateEntry]:
        return self._run_async(self._async_client.get_state_for_tx(tx_hash))

    def get_state_for_block(
        self,
        block_ref: str | int,
    ) -> list[StateEntry]:
        return self._run_async(
            self._async_client.get_state_for_block(block_ref)
        )

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

    def watch_blocks(
        self,
        *,
        start_height: int | None = None,
        poll_interval_seconds: float | None = None,
    ) -> _SyncAsyncIterator[IndexedBlock]:
        return _SyncAsyncIterator(
            self,
            self._async_client.watch_blocks(
                start_height=start_height,
                poll_interval_seconds=poll_interval_seconds,
            ),
        )

    def watch_events(
        self,
        contract: str,
        event: str,
        *,
        after_id: int | None = None,
        limit: int | None = None,
        poll_interval_seconds: float | None = None,
    ) -> _SyncAsyncIterator[IndexedEvent]:
        return _SyncAsyncIterator(
            self,
            self._async_client.watch_events(
                contract,
                event,
                after_id=after_id,
                limit=limit,
                poll_interval_seconds=poll_interval_seconds,
            ),
        )

    def watch_live_events(
        self,
        contract: str,
        event: str,
        *,
        poll_interval_seconds: float | None = None,
    ) -> _SyncAsyncIterator[LiveEvent]:
        return _SyncAsyncIterator(
            self,
            self._async_client.watch_live_events(
                contract,
                event,
                poll_interval_seconds=poll_interval_seconds,
            ),
        )
