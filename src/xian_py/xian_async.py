import asyncio
import math
from decimal import Decimal
from typing import Any, Literal, Optional

import aiohttp
from xian_runtime_types.decimal import ContractingDecimal
from xian_runtime_types.encoding import decode

import xian_py.transaction as tr
from xian_py.decompiler import ContractDecompiler
from xian_py.exception import XianException
from xian_py.models import (
    BdsStatus,
    IndexedBlock,
    IndexedEvent,
    IndexedTransaction,
    PerformanceStatus,
    StateEntry,
    TransactionReceipt,
    TransactionSubmission,
)
from xian_py.wallet import Wallet


class XianAsync:
    """Async version of the Xian class for non-blocking operations."""

    DEFAULT_STAMP_MARGIN = 0.10
    DEFAULT_MIN_STAMP_HEADROOM = 10

    def __init__(
        self,
        node_url: str,
        chain_id: str = None,
        wallet: Wallet = None,
        *,
        session: Optional[aiohttp.ClientSession] = None,
        timeout: Optional[aiohttp.ClientTimeout] = None,
        connector: Optional[aiohttp.TCPConnector] = None,
    ):
        self.node_url = node_url.rstrip("/")
        self.chain_id = chain_id
        self.wallet = wallet if wallet else Wallet()
        self._chain_id_set = chain_id is not None
        self._external_session = session
        self._timeout = timeout or aiohttp.ClientTimeout(
            total=15, sock_connect=3, sock_read=10
        )
        self._connector_params = connector
        self._session: Optional[aiohttp.ClientSession] = session
        self._nonce_lock: asyncio.Lock | None = None
        self._next_nonce: int | None = None

    @property
    def _nonce_reservation_lock(self) -> asyncio.Lock:
        if self._nonce_lock is None:
            self._nonce_lock = asyncio.Lock()
        return self._nonce_lock

    async def __aenter__(self) -> "XianAsync":
        if self._session is None:
            connector = self._connector_params or aiohttp.TCPConnector(
                limit=100, ttl_dns_cache=300
            )
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                connector=connector,
            )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            connector = self._connector_params or aiohttp.TCPConnector(
                limit=100, ttl_dns_cache=300
            )
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                connector=connector,
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._external_session:
            await self._session.close()
        self._session = None

    async def ensure_chain_id(self) -> None:
        if not self._chain_id_set:
            self.chain_id = await self.get_chain_id()
            self._chain_id_set = True

    async def _abci_query_value(self, path: str) -> Any:
        data = await tr.abci_query_async(
            self.node_url,
            path,
            session=self.session,
        )
        response = data["result"]["response"]
        byte_string = response["value"]
        type_of_data = response.get("info")

        if byte_string is None or byte_string == "AA==":
            return None

        return self._decode_abci_value(
            tr.decode_str(byte_string),
            type_of_data,
        )

    async def refresh_nonce(self) -> int:
        """Refresh and return the next nonce from the node."""
        nonce = await tr.get_nonce_async(
            self.node_url,
            self.wallet.public_key,
            session=self.session,
        )
        async with self._nonce_reservation_lock:
            self._next_nonce = nonce
        return nonce

    async def get_tx(self, tx_hash: str) -> TransactionReceipt:
        """Return a decoded transaction receipt."""
        data = await tr.get_tx_async(
            self.node_url,
            tx_hash,
            session=self.session,
        )
        return self._normalize_tx_lookup(data)

    async def get_balance(
        self,
        address: str = None,
        contract: str = "currency",
    ) -> int | ContractingDecimal:
        address = address or self.wallet.public_key

        async def query_simulate() -> Any:
            payload = {
                "contract": contract,
                "function": "balance_of",
                "kwargs": {"address": address},
                "sender": self.wallet.public_key,
            }
            data = await tr.simulate_tx_async(
                self.node_url,
                payload,
                session=self.session,
            )
            return data["result"]

        async def query_abci() -> Any:
            return await self._abci_query_value(
                f"/get/{contract}.balances:{address}"
            )

        def normalize_balance(
            balance: int | float | str | ContractingDecimal,
        ) -> int | ContractingDecimal:
            if isinstance(balance, ContractingDecimal):
                return balance
            if isinstance(balance, int):
                return balance
            if isinstance(balance, float):
                if balance.is_integer():
                    return int(balance)
                return ContractingDecimal(str(balance))
            if isinstance(balance, str):
                if balance.isdigit():
                    return int(balance)
                return ContractingDecimal(balance)
            raise TypeError(f"Unsupported balance type: {type(balance)}")

        try:
            return normalize_balance(await query_simulate())
        except Exception:
            try:
                return normalize_balance(await query_abci())
            except Exception as exc:
                raise XianException(exc) from exc

    def _normalize_tx_lookup(self, data: dict[str, Any]) -> TransactionReceipt:
        normalized = dict(data)
        result = normalized.get("result", {})
        tx = result.get("tx")
        tx_result = result.get("tx_result", {})
        execution = tx_result.get("data")

        if tx is not None:
            normalized["transaction"] = tx
        if isinstance(execution, dict):
            normalized["execution"] = execution

        if "error" in normalized:
            normalized["success"] = False
            normalized["message"] = normalized["error"].get(
                "data"
            ) or normalized["error"].get("message")
        elif tx_result.get("code") == 0:
            normalized["success"] = True
        else:
            normalized["success"] = False
            if isinstance(execution, dict):
                normalized["message"] = (
                    execution.get("result")
                    or execution.get("error")
                    or execution
                )
            elif execution is not None:
                normalized["message"] = execution
            else:
                normalized["message"] = (
                    tx_result.get("log") or "Transaction failed"
                )

        return TransactionReceipt.from_lookup(normalized)

    async def wait_for_tx(
        self,
        tx_hash: str,
        *,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.25,
    ) -> TransactionReceipt:
        """Wait until a transaction can be retrieved from the node."""
        data = await tr.wait_for_tx_async(
            self.node_url,
            tx_hash,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            session=self.session,
        )
        return self._normalize_tx_lookup(data)

    async def estimate_stamps(
        self,
        contract: str,
        function: str,
        kwargs: dict,
        *,
        stamp_margin: float = DEFAULT_STAMP_MARGIN,
        min_stamp_headroom: int = DEFAULT_MIN_STAMP_HEADROOM,
    ) -> dict[str, Any]:
        payload = {
            "contract": contract,
            "function": function,
            "kwargs": kwargs,
            "sender": self.wallet.public_key,
        }
        simulation = await tr.simulate_tx_async(
            self.node_url,
            payload,
            session=self.session,
        )
        estimated = int(simulation["stamps_used"])
        suggested = self._apply_stamp_headroom(
            estimated,
            stamp_margin=stamp_margin,
            min_stamp_headroom=min_stamp_headroom,
        )
        return {
            "estimated": estimated,
            "suggested": suggested,
            "simulation": simulation,
        }

    async def _reserve_nonce(self, explicit_nonce: int | None) -> int:
        if explicit_nonce is not None:
            async with self._nonce_reservation_lock:
                if self._next_nonce is None or explicit_nonce >= self._next_nonce:
                    self._next_nonce = explicit_nonce + 1
            return explicit_nonce

        async with self._nonce_reservation_lock:
            if self._next_nonce is None:
                self._next_nonce = await tr.get_nonce_async(
                    self.node_url,
                    self.wallet.public_key,
                    session=self.session,
                )
            nonce = self._next_nonce
            self._next_nonce += 1
            return nonce

    async def _invalidate_reserved_nonce(self, nonce: int) -> None:
        async with self._nonce_reservation_lock:
            if self._next_nonce is not None and nonce < self._next_nonce:
                self._next_nonce = None

    @classmethod
    def _apply_stamp_headroom(
        cls,
        estimated: int,
        *,
        stamp_margin: float,
        min_stamp_headroom: int,
    ) -> int:
        if stamp_margin < 0:
            raise ValueError("stamp_margin must be >= 0")
        if min_stamp_headroom < 0:
            raise ValueError("min_stamp_headroom must be >= 0")

        proportional = math.ceil(estimated * stamp_margin)
        headroom = max(proportional, min_stamp_headroom)
        return estimated + headroom

    async def send_tx(
        self,
        contract: str,
        function: str,
        kwargs: dict,
        stamps: int | None = None,
        nonce: int = None,
        chain_id: str = None,
        mode: Literal["async", "checktx", "commit"] = "checktx",
        wait_for_tx: bool = False,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.25,
        stamp_margin: float = DEFAULT_STAMP_MARGIN,
        min_stamp_headroom: int = DEFAULT_MIN_STAMP_HEADROOM,
    ) -> TransactionSubmission:
        """Send a transaction using an explicit broadcast mode."""
        if mode not in {"async", "checktx", "commit"}:
            raise ValueError("mode must be one of: 'async', 'checktx', 'commit'")

        if chain_id is None:
            await self.ensure_chain_id()
            chain_id = self.chain_id

        estimated_stamps: int | None = None
        supplied_stamps = stamps
        if supplied_stamps is None:
            stamp_estimate = await self.estimate_stamps(
                contract,
                function,
                kwargs,
                stamp_margin=stamp_margin,
                min_stamp_headroom=min_stamp_headroom,
            )
            estimated_stamps = stamp_estimate["estimated"]
            supplied_stamps = stamp_estimate["suggested"]

        reserved_nonce = await self._reserve_nonce(nonce)
        payload = {
            "chain_id": chain_id,
            "contract": contract,
            "function": function,
            "kwargs": kwargs,
            "nonce": reserved_nonce,
            "sender": self.wallet.public_key,
            "stamps_supplied": supplied_stamps,
        }

        tx = tr.create_tx(payload, self.wallet)

        try:
            if mode == "async":
                data = await tr.broadcast_tx_nowait_async(
                    self.node_url,
                    tx,
                    session=self.session,
                )
            elif mode == "commit":
                data = await tr.broadcast_tx_commit_async(
                    self.node_url,
                    tx,
                    session=self.session,
                )
            else:
                data = await tr.broadcast_tx_wait_async(
                    self.node_url,
                    tx,
                    session=self.session,
                )
        except Exception:
            await self._invalidate_reserved_nonce(reserved_nonce)
            raise

        result: dict[str, Any] = {
            "submitted": False,
            "accepted": False,
            "finalized": False,
            "message": None,
            "tx_hash": None,
            "mode": mode,
            "nonce": reserved_nonce,
            "stamps_supplied": supplied_stamps,
            "stamps_estimated": estimated_stamps,
            "response": data,
            "receipt": None,
        }

        if "error" in data:
            await self._invalidate_reserved_nonce(reserved_nonce)
            result["message"] = data["error"].get("data") or data["error"].get(
                "message"
            )
            return TransactionSubmission.from_dict(result)

        result["submitted"] = True

        if mode == "commit":
            commit_result = data.get("result", {})
            check_tx = commit_result.get("check_tx", {})
            deliver_tx = (
                commit_result.get("deliver_tx")
                or commit_result.get("tx_result")
                or {}
            )
            result["tx_hash"] = commit_result.get("hash")
            result["accepted"] = check_tx.get("code", 1) == 0
            result["finalized"] = deliver_tx.get("code", 1) == 0
            if not result["accepted"]:
                await self._invalidate_reserved_nonce(reserved_nonce)
                result["message"] = check_tx.get("log") or "CheckTx failed"
            elif not result["finalized"]:
                result["message"] = deliver_tx.get("log") or "DeliverTx failed"
            return TransactionSubmission.from_dict(result)

        checktx_result = data.get("result", {})
        result["tx_hash"] = checktx_result.get("hash")
        if mode == "async":
            result["accepted"] = None
            if wait_for_tx and result["tx_hash"] is not None:
                receipt = await self.wait_for_tx(
                    result["tx_hash"],
                    timeout_seconds=timeout_seconds,
                    poll_interval_seconds=poll_interval_seconds,
                )
                result["receipt"] = receipt
                result["finalized"] = True
            return TransactionSubmission.from_dict(result)

        result["accepted"] = checktx_result.get("code", 1) == 0
        if not result["accepted"]:
            await self._invalidate_reserved_nonce(reserved_nonce)
            result["message"] = checktx_result.get("log") or "CheckTx failed"
            return TransactionSubmission.from_dict(result)

        if wait_for_tx and result["tx_hash"] is not None:
            receipt = await self.wait_for_tx(
                result["tx_hash"],
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
            result["receipt"] = receipt
            result["finalized"] = True

        return TransactionSubmission.from_dict(result)

    async def send(
        self,
        amount: int | float | str | Decimal | ContractingDecimal,
        to_address: str,
        token: str = "currency",
        stamps: int | None = None,
        mode: Literal["async", "checktx", "commit"] = "checktx",
        wait_for_tx: bool = False,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.25,
        stamp_margin: float = DEFAULT_STAMP_MARGIN,
        min_stamp_headroom: int = DEFAULT_MIN_STAMP_HEADROOM,
    ) -> TransactionSubmission:
        """Send a token to a given address."""
        return await self.send_tx(
            token,
            "transfer",
            {"amount": self._coerce_amount(amount), "to": to_address},
            stamps=stamps,
            mode=mode,
            wait_for_tx=wait_for_tx,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            stamp_margin=stamp_margin,
            min_stamp_headroom=min_stamp_headroom,
        )

    async def simulate(self, contract: str, function: str, kwargs: dict) -> dict:
        payload = {
            "contract": contract,
            "function": function,
            "kwargs": kwargs,
            "sender": self.wallet.public_key,
        }
        return await tr.simulate_tx_async(
            self.node_url,
            payload,
            session=self.session,
        )

    async def get_state(
        self,
        contract: str,
        variable: str,
        *keys: str,
    ) -> None | int | ContractingDecimal | dict | list | str:
        """Retrieve contract state and decode it."""
        path = f"/get/{contract}.{variable}"
        if keys:
            path = f"{path}:{':'.join(keys)}"
        return await self._abci_query_value(path)

    async def get_contract(self, contract: str, clean: bool = False) -> None | str:
        """Retrieve contract source and decode it."""
        response = await tr.abci_query_async(
            self.node_url,
            f"/contract/{contract}",
            session=self.session,
        )
        byte_string = response["result"]["response"]["value"]

        if byte_string is None or byte_string == "AA==":
            return None

        code = tr.decode_str(byte_string)
        if clean:
            return ContractDecompiler().decompile(code)
        return code

    async def get_approved_amount(
        self,
        contract: str,
        address: str = None,
        token: str = "currency",
    ) -> int | ContractingDecimal:
        """Retrieve approved token amount for a contract."""
        address = address if address else self.wallet.public_key

        value = await self.get_state(token, "approvals", address, contract)
        if value is None:
            value = await self.get_state(token, "balances", address, contract)

        return 0 if value is None else value

    async def approve(
        self,
        contract: str,
        token: str = "currency",
        amount: int | float | str | Decimal | ContractingDecimal = 999999999999,
        stamps: int | None = None,
        mode: Literal["async", "checktx", "commit"] = "checktx",
        wait_for_tx: bool = False,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.25,
        stamp_margin: float = DEFAULT_STAMP_MARGIN,
        min_stamp_headroom: int = DEFAULT_MIN_STAMP_HEADROOM,
    ) -> TransactionSubmission:
        """Approve a contract to spend a token amount."""
        return await self.send_tx(
            token,
            "approve",
            {"amount": self._coerce_amount(amount), "to": contract},
            stamps=stamps,
            mode=mode,
            wait_for_tx=wait_for_tx,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            stamp_margin=stamp_margin,
            min_stamp_headroom=min_stamp_headroom,
        )

    async def submit_contract(
        self,
        name: str,
        code: str,
        args: dict = None,
        stamps: int | None = None,
        mode: Literal["async", "checktx", "commit"] = "checktx",
        wait_for_tx: bool = False,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.25,
        stamp_margin: float = DEFAULT_STAMP_MARGIN,
        min_stamp_headroom: int = DEFAULT_MIN_STAMP_HEADROOM,
    ) -> TransactionSubmission:
        """Submit a contract to the network."""
        kwargs: dict[str, Any] = {"name": name, "code": code}
        if args:
            kwargs["constructor_args"] = args

        return await self.send_tx(
            "submission",
            "submit_contract",
            kwargs,
            stamps=stamps,
            mode=mode,
            wait_for_tx=wait_for_tx,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            stamp_margin=stamp_margin,
            min_stamp_headroom=min_stamp_headroom,
        )

    async def get_nodes(self) -> list[str]:
        """Retrieve the peer IPs from the network."""
        response = await tr.request_json_async(
            "POST",
            f"{self.node_url}/net_info",
            session=self.session,
            raise_for_status=True,
        )
        peers = response["result"]["peers"]
        return [peer["remote_ip"] for peer in peers]

    async def get_genesis(self) -> dict[str, Any]:
        """Retrieve genesis info from the network."""
        return await tr.request_json_async(
            "POST",
            f"{self.node_url}/genesis",
            session=self.session,
            raise_for_status=True,
        )

    async def get_chain_id(self) -> str:
        """Retrieve chain_id from the network."""
        genesis = await self.get_genesis()
        return genesis["result"]["genesis"]["chain_id"]

    async def get_perf_status(self) -> PerformanceStatus:
        payload = await self._abci_query_value("/perf_status")
        if not isinstance(payload, dict):
            raise XianException("Unexpected perf status payload")
        return PerformanceStatus.from_dict(payload)

    async def get_bds_status(self) -> BdsStatus:
        payload = await self._abci_query_value("/bds_status")
        if not isinstance(payload, dict):
            raise XianException("Unexpected BDS status payload")
        return BdsStatus.from_dict(payload)

    async def list_blocks(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IndexedBlock]:
        payload = await self._abci_query_value(
            f"/blocks/limit={limit}/offset={offset}"
        )
        if not isinstance(payload, list):
            raise XianException("Unexpected block list payload")
        return [IndexedBlock.from_dict(item) for item in payload]

    async def get_block(self, height: int) -> IndexedBlock | None:
        payload = await self._abci_query_value(f"/block/{height}")
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise XianException("Unexpected block payload")
        return IndexedBlock.from_dict(payload)

    async def get_block_by_hash(self, block_hash: str) -> IndexedBlock | None:
        payload = await self._abci_query_value(f"/block_by_hash/{block_hash}")
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise XianException("Unexpected block payload")
        return IndexedBlock.from_dict(payload)

    async def get_indexed_tx(self, tx_hash: str) -> IndexedTransaction | None:
        payload = await self._abci_query_value(f"/tx/{tx_hash}")
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise XianException("Unexpected indexed transaction payload")
        return IndexedTransaction.from_dict(payload)

    async def list_txs_for_block(
        self,
        block_ref: str | int,
    ) -> list[IndexedTransaction]:
        payload = await self._abci_query_value(f"/txs_for_block/{block_ref}")
        if not isinstance(payload, list):
            raise XianException("Unexpected block transaction list payload")
        return [IndexedTransaction.from_dict(item) for item in payload]

    async def list_txs_by_sender(
        self,
        sender: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IndexedTransaction]:
        payload = await self._abci_query_value(
            f"/txs_by_sender/{sender}/limit={limit}/offset={offset}"
        )
        if not isinstance(payload, list):
            raise XianException("Unexpected sender transaction list payload")
        return [IndexedTransaction.from_dict(item) for item in payload]

    async def list_txs_by_contract(
        self,
        contract: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IndexedTransaction]:
        payload = await self._abci_query_value(
            f"/txs_by_contract/{contract}/limit={limit}/offset={offset}"
        )
        if not isinstance(payload, list):
            raise XianException("Unexpected contract transaction list payload")
        return [IndexedTransaction.from_dict(item) for item in payload]

    async def get_events_for_tx(self, tx_hash: str) -> list[IndexedEvent]:
        payload = await self._abci_query_value(f"/events_for_tx/{tx_hash}")
        if not isinstance(payload, list):
            raise XianException("Unexpected event list payload")
        return [IndexedEvent.from_dict(item) for item in payload]

    async def list_events(
        self,
        contract: str,
        event: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[IndexedEvent]:
        payload = await self._abci_query_value(
            f"/events/{contract}/{event}/limit={limit}/offset={offset}"
        )
        if not isinstance(payload, list):
            raise XianException("Unexpected event list payload")
        return [IndexedEvent.from_dict(item) for item in payload]

    async def get_state_history(
        self,
        key: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StateEntry]:
        payload = await self._abci_query_value(
            f"/state_history/{key}/limit={limit}/offset={offset}"
        )
        if not isinstance(payload, list):
            raise XianException("Unexpected state history payload")
        return [StateEntry.from_dict(item) for item in payload]

    async def get_state_for_tx(self, tx_hash: str) -> list[StateEntry]:
        payload = await self._abci_query_value(f"/state_for_tx/{tx_hash}")
        if not isinstance(payload, list):
            raise XianException("Unexpected state-for-tx payload")
        return [StateEntry.from_dict(item) for item in payload]

    async def get_state_for_block(
        self,
        block_ref: str | int,
    ) -> list[StateEntry]:
        payload = await self._abci_query_value(f"/state_for_block/{block_ref}")
        if not isinstance(payload, list):
            raise XianException("Unexpected state-for-block payload")
        return [StateEntry.from_dict(item) for item in payload]

    @staticmethod
    def _coerce_amount(
        amount: int | float | str | Decimal | ContractingDecimal,
    ) -> int | ContractingDecimal:
        if isinstance(amount, ContractingDecimal):
            return amount
        if isinstance(amount, Decimal):
            return ContractingDecimal(str(amount))
        if isinstance(amount, int):
            return amount
        if isinstance(amount, float):
            if amount.is_integer():
                return int(amount)
            return ContractingDecimal(str(amount))
        if isinstance(amount, str):
            if amount.isdigit():
                return int(amount)
            return ContractingDecimal(amount)
        raise TypeError(f"Unsupported amount type: {type(amount)}")

    @staticmethod
    def _decode_abci_value(
        data: str,
        type_of_data: str | None,
    ) -> int | ContractingDecimal | dict | list | str:
        if type_of_data == "int":
            return int(data)
        if type_of_data == "decimal":
            return ContractingDecimal(data)
        if type_of_data in {"dict", "list"}:
            return decode(data)
        if type_of_data == "str":
            return data

        try:
            return decode(data)
        except Exception:
            return data
