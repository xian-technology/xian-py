import ast
import asyncio
import json
import math
import re
from decimal import Decimal
from typing import Any, Literal, Optional
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from xian_runtime_types.decimal import ContractingDecimal
from xian_runtime_types.encoding import decode

import xian_py.transaction as tr
from xian_py.application_clients import (
    AsyncContractClient,
    AsyncEventClient,
    AsyncStateKeyClient,
    AsyncTokenClient,
)
from xian_py.config import (
    SubmissionConfig,
    XianClientConfig,
)
from xian_py.exception import (
    RpcError,
    SimulationError,
    TransportError,
    XianException,
)
from xian_py.models import (
    BdsStatus,
    DeveloperRewardSummary,
    IndexedBlock,
    IndexedEvent,
    IndexedTransaction,
    LiveEvent,
    NodeStatus,
    PerformanceStatus,
    ShieldedOutputTag,
    ShieldedWalletHistoryEntry,
    StateEntry,
    TokenBalancePage,
    TransactionReceipt,
    TransactionSubmission,
)
from xian_py.wallet import Wallet

_SIMULATION_DATETIME_RE = re.compile(
    r"(?<=:\s)(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)(?=[,}])"
)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _rpc_ws_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme:
        parsed = urlsplit(f"http://{url}")
    scheme = parsed.scheme.lower()

    if scheme in {"http", "ws"}:
        ws_scheme = "ws"
    elif scheme in {"https", "wss"}:
        ws_scheme = "wss"
    else:
        raise ValueError("websocket_url must use http(s):// or ws(s):// scheme")

    path = parsed.path.rstrip("/")
    if path.endswith("/websocket"):
        resolved_path = path
    elif not path:
        resolved_path = "/websocket"
    else:
        resolved_path = f"{path}/websocket"

    return urlunsplit((ws_scheme, parsed.netloc, resolved_path, "", ""))


def _rpc_graphql_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme:
        parsed = urlsplit(f"http://{url}")
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("node_url must use http(s):// scheme")

    path = parsed.path.rstrip("/")
    if path.endswith("/graphql"):
        resolved_path = path
    elif not path:
        resolved_path = "/graphql"
    else:
        resolved_path = f"{path}/graphql"

    return urlunsplit((scheme, parsed.netloc, resolved_path, "", ""))


def _quote_cometbft_query_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _build_cometbft_event_query(contract: str, event: str) -> str:
    return (
        "tm.event='Tx' "
        f"AND {event}.contract={_quote_cometbft_query_value(contract)}"
    )


def _decode_ws_tx_execution(payload: dict[str, Any]) -> dict[str, Any] | None:
    tx_result = (
        payload.get("result", {})
        .get("data", {})
        .get("value", {})
        .get("TxResult", {})
        .get("result", {})
    )
    encoded = tx_result.get("data") if isinstance(tx_result, dict) else None
    if not isinstance(encoded, str) or not encoded:
        return None
    try:
        decoded = tr.decode_str(encoded)
    except Exception:
        return None
    try:
        parsed = ast.literal_eval(decoded)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    try:
        loaded = json.loads(decoded)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _ws_tx_metadata(
    payload: dict[str, Any],
) -> tuple[str | None, int | None, int | None]:
    ws_result = payload.get("result", {})
    value = ws_result.get("data", {}).get("value", {})
    tx_result = value.get("TxResult", {})
    result = tx_result.get("result", {})
    execution = _decode_ws_tx_execution(payload)
    tx_hash = None
    ws_events = ws_result.get("events")
    if isinstance(ws_events, dict):
        tx_hash_values = ws_events.get("tx.hash")
        if isinstance(tx_hash_values, list) and tx_hash_values:
            first_tx_hash = tx_hash_values[0]
            if isinstance(first_tx_hash, str):
                tx_hash = first_tx_hash
        elif isinstance(tx_hash_values, str):
            tx_hash = tx_hash_values
    if not isinstance(tx_hash, str):
        tx_hash = result.get("hash")
    if not isinstance(tx_hash, str):
        tx_hash = tx_result.get("hash")
    if not isinstance(tx_hash, str):
        tx_hash = execution.get("hash") if isinstance(execution, dict) else None
    block_height = _coerce_int(tx_result.get("height") or value.get("height"))
    tx_index = _coerce_int(tx_result.get("index"))
    return tx_hash if isinstance(tx_hash, str) else None, block_height, tx_index


def _extract_matching_live_events(
    payload: dict[str, Any],
    *,
    contract: str,
    event: str,
) -> list[LiveEvent]:
    execution = _decode_ws_tx_execution(payload)
    if not isinstance(execution, dict):
        return []
    tx_hash, block_height, tx_index = _ws_tx_metadata(payload)
    events = execution.get("events")
    if not isinstance(events, list):
        return []

    matched: list[LiveEvent] = []
    for event_index, item in enumerate(events):
        if not isinstance(item, dict):
            continue
        item_contract = str(item.get("contract", ""))
        item_event = str(item.get("event", "ContractEvent"))
        if item_contract != contract or item_event != event:
            continue

        data_indexed = item.get("data_indexed")
        normalized_indexed = (
            dict(data_indexed) if isinstance(data_indexed, dict) else None
        )
        data = item.get("data")
        normalized_data = dict(data) if isinstance(data, dict) else None

        matched.append(
            LiveEvent(
                tx_hash=tx_hash,
                block_height=block_height,
                tx_index=tx_index,
                event_index=event_index,
                contract=item_contract,
                event=item_event,
                signer=item.get("signer"),
                caller=item.get("caller"),
                data_indexed=normalized_indexed,
                data=normalized_data,
                raw=dict(item),
            )
        )
    return matched


def _graphql_event_node_to_dict(node: dict[str, Any]) -> dict[str, Any]:
    transaction = node.get("transactionByTxHash")
    block_height = None
    if isinstance(transaction, dict):
        block_height = _coerce_int(transaction.get("blockHeight"))

    return {
        "id": _coerce_int(node.get("id")),
        "tx_hash": node.get("txHash"),
        "block_height": block_height,
        "tx_index": None,
        "event_index": None,
        "contract": node.get("contract"),
        "event": node.get("event"),
        "signer": node.get("signer"),
        "caller": node.get("caller"),
        "data_indexed": node.get("dataIndexed"),
        "data": node.get("data"),
        "created": node.get("created"),
        "raw": dict(node),
    }


def _validate_xian_wallet(wallet: Any) -> None:
    public_key = getattr(wallet, "public_key", None)
    sign_msg = getattr(wallet, "sign_msg", None)
    if (
        not callable(sign_msg)
        or not isinstance(public_key, str)
        or not Wallet.is_valid_key(public_key)
    ):
        raise TypeError(
            "wallet must expose an Ed25519 Xian account; use xian_py.Wallet "
            "or an equivalent signer with an Ed25519 public_key"
        )


class XianAsync:
    """Async version of the Xian class for non-blocking operations."""

    DEFAULT_CHI_MARGIN = SubmissionConfig().chi_margin
    DEFAULT_MIN_CHI_HEADROOM = SubmissionConfig().min_chi_headroom

    def __init__(
        self,
        node_url: str,
        chain_id: str = None,
        wallet: Wallet = None,
        *,
        config: XianClientConfig | None = None,
        session: Optional[aiohttp.ClientSession] = None,
        timeout: Optional[aiohttp.ClientTimeout] = None,
        connector: Optional[aiohttp.TCPConnector] = None,
    ):
        self.node_url = node_url.rstrip("/")
        self.chain_id = chain_id
        self.wallet = wallet if wallet else Wallet()
        _validate_xian_wallet(self.wallet)
        self.config = config or XianClientConfig()
        self._chain_id_set = chain_id is not None
        self._external_session = session
        transport = self.config.transport
        self._timeout = timeout or aiohttp.ClientTimeout(
            total=transport.total_timeout_seconds,
            sock_connect=transport.connect_timeout_seconds,
            sock_read=transport.read_timeout_seconds,
        )
        self._connector = connector
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
            transport = self.config.transport
            connector = self._connector or aiohttp.TCPConnector(
                limit=transport.connection_limit,
                ttl_dns_cache=transport.dns_cache_ttl_seconds,
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
            transport = self.config.transport
            connector = self._connector or aiohttp.TCPConnector(
                limit=transport.connection_limit,
                ttl_dns_cache=transport.dns_cache_ttl_seconds,
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

    def _resolve_cometbft_ws_url(self) -> str:
        websocket_url = self.config.watcher.websocket_url
        if websocket_url is None:
            websocket_url = self.node_url
        return _rpc_ws_url(websocket_url)

    def _resolve_bds_graphql_url(self) -> str:
        return _rpc_graphql_url(self.node_url)

    async def _graphql_query(
        self,
        query: str,
        *,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        async def do_request() -> dict[str, Any]:
            try:
                async with self.session.post(
                    self._resolve_bds_graphql_url(),
                    json={"query": query, "variables": variables},
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if hasattr(response, "raise_for_status"):
                        response.raise_for_status()
                    payload = await response.json()
            except XianException:
                raise
            except Exception as exc:
                raise TransportError(exc) from exc

            if not isinstance(payload, dict):
                raise XianException("Unexpected GraphQL payload")
            if "errors" in payload:
                raise XianException(
                    "GraphQL query failed",
                    details={"errors": payload["errors"]},
                )

            data = payload.get("data")
            if not isinstance(data, dict):
                raise XianException("Unexpected GraphQL payload")
            return data

        return await self._retry_read(do_request)

    async def _graphql_list_events(
        self,
        contract: str,
        event: str,
        *,
        limit: int,
        offset: int,
        after_id: int | None,
    ) -> list[IndexedEvent]:
        query = """
        query ListEvents(
          $contract: String!
          $event: String!
          $limit: Int!
          $offset: Int!
        ) {
          allEvents(
            first: $limit
            offset: $offset
            orderBy: ID_ASC
            condition: {contract: $contract, event: $event}
          ) {
            edges {
              node {
                id
                txHash
                contract
                event
                signer
                caller
                dataIndexed
                data
                created
                transactionByTxHash {
                  blockHeight
                }
              }
            }
          }
        }
        """
        variables: dict[str, Any] = {
            "contract": contract,
            "event": event,
            "limit": limit,
            "offset": offset,
        }

        if after_id is not None:
            query = """
            query ListEventsAfter(
              $contract: String!
              $event: String!
              $limit: Int!
              $afterId: Int!
            ) {
              allEvents(
                first: $limit
                orderBy: ID_ASC
                condition: {contract: $contract, event: $event}
                filter: {id: {greaterThan: $afterId}}
              ) {
                edges {
                  node {
                    id
                    txHash
                    contract
                    event
                    signer
                    caller
                    dataIndexed
                    data
                    created
                    transactionByTxHash {
                      blockHeight
                    }
                  }
                }
              }
            }
            """
            variables = {
                "contract": contract,
                "event": event,
                "limit": limit,
                "afterId": after_id,
            }

        data = await self._graphql_query(query, variables=variables)
        edges = data.get("allEvents", {}).get("edges", [])
        if not isinstance(edges, list):
            raise XianException("Unexpected GraphQL event payload")

        events: list[IndexedEvent] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node")
            if not isinstance(node, dict):
                continue
            events.append(
                IndexedEvent.from_dict(_graphql_event_node_to_dict(node))
            )
        return events

    async def _graphql_get_events_for_tx(
        self,
        tx_hash: str,
    ) -> list[IndexedEvent]:
        query = """
        query EventsForTx($txHash: String!) {
          allEvents(
            first: 1000
            orderBy: ID_ASC
            filter: {txHash: {equalTo: $txHash}}
          ) {
            edges {
              node {
                id
                txHash
                contract
                event
                signer
                caller
                dataIndexed
                data
                created
                transactionByTxHash {
                  blockHeight
                }
              }
            }
          }
        }
        """
        data = await self._graphql_query(query, variables={"txHash": tx_hash})
        edges = data.get("allEvents", {}).get("edges", [])
        if not isinstance(edges, list):
            raise XianException("Unexpected GraphQL event payload")

        events: list[IndexedEvent] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node")
            if not isinstance(node, dict):
                continue
            events.append(
                IndexedEvent.from_dict(_graphql_event_node_to_dict(node))
            )
        return events

    async def ensure_chain_id(self) -> None:
        if not self._chain_id_set:
            self.chain_id = await self.get_chain_id()
            self._chain_id_set = True

    async def _retry_read(self, operation):
        retry = self.config.retry
        attempts = max(retry.max_attempts, 1)
        delay = max(retry.initial_delay_seconds, 0.0)

        for attempt in range(1, attempts + 1):
            try:
                return await operation()
            except Exception as exc:
                if (
                    not self._is_retryable_read_error(exc)
                    or attempt >= attempts
                ):
                    raise
                if delay > 0:
                    await asyncio.sleep(delay)
                delay = min(
                    max(delay * retry.backoff_multiplier, delay),
                    retry.max_delay_seconds,
                )

    async def _retry_broadcast(self, operation):
        retry = self.config.retry
        attempts = max(retry.max_attempts, 1)
        delay = max(retry.initial_delay_seconds, 0.0)

        for attempt in range(1, attempts + 1):
            try:
                return await operation()
            except Exception as exc:
                if (
                    not retry.retry_transport_errors
                    or not isinstance(exc, TransportError)
                    or attempt >= attempts
                ):
                    raise
                if delay > 0:
                    await asyncio.sleep(delay)
                delay = min(
                    max(delay * retry.backoff_multiplier, delay),
                    retry.max_delay_seconds,
                )

    def _is_retryable_read_error(self, exc: Exception) -> bool:
        retry = self.config.retry
        if retry.retry_transport_errors and isinstance(exc, TransportError):
            return True
        if retry.retry_rpc_errors and isinstance(exc, RpcError):
            return True
        return False

    async def _abci_query_value(self, path: str) -> Any:
        data = await self._retry_read(
            lambda: tr.abci_query_async(
                self.node_url,
                path,
                session=self.session,
            )
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
        nonce = await self._retry_read(
            lambda: tr.get_nonce_async(
                self.node_url,
                self.wallet.public_key,
                session=self.session,
            )
        )
        async with self._nonce_reservation_lock:
            self._next_nonce = nonce
        return nonce

    async def get_tx(self, tx_hash: str) -> TransactionReceipt:
        """Return a decoded transaction receipt."""
        data = await self._retry_read(
            lambda: tr.get_tx_async(
                self.node_url,
                tx_hash,
                session=self.session,
            )
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
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ) -> TransactionReceipt:
        """Wait until a transaction can be retrieved from the node."""
        timeout_seconds = (
            self.config.submission.timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        poll_interval_seconds = (
            self.config.submission.poll_interval_seconds
            if poll_interval_seconds is None
            else poll_interval_seconds
        )
        data = await self._retry_read(
            lambda: tr.wait_for_tx_async(
                self.node_url,
                tx_hash,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                session=self.session,
            )
        )
        return self._normalize_tx_lookup(data)

    async def estimate_chi(
        self,
        contract: str,
        function: str,
        kwargs: dict,
        *,
        chi_margin: float | None = None,
        min_chi_headroom: int | None = None,
    ) -> dict[str, Any]:
        chi_margin = (
            self.config.submission.chi_margin
            if chi_margin is None
            else chi_margin
        )
        min_chi_headroom = (
            self.config.submission.min_chi_headroom
            if min_chi_headroom is None
            else min_chi_headroom
        )
        payload = {
            "contract": contract,
            "function": function,
            "kwargs": kwargs,
            "sender": self.wallet.public_key,
        }
        simulation = await self._retry_read(
            lambda: tr.simulate_tx_async(
                self.node_url,
                payload,
                session=self.session,
            )
        )
        estimated = int(simulation["chi_used"])
        suggested = self._apply_chi_headroom(
            estimated,
            chi_margin=chi_margin,
            min_chi_headroom=min_chi_headroom,
        )
        return {
            "estimated": estimated,
            "suggested": suggested,
            "simulation": simulation,
        }

    async def _reserve_nonce(self, explicit_nonce: int | None) -> int:
        if explicit_nonce is not None:
            async with self._nonce_reservation_lock:
                if (
                    self._next_nonce is None
                    or explicit_nonce >= self._next_nonce
                ):
                    self._next_nonce = explicit_nonce + 1
            return explicit_nonce

        async with self._nonce_reservation_lock:
            if self._next_nonce is None:
                self._next_nonce = await self._retry_read(
                    lambda: tr.get_nonce_async(
                        self.node_url,
                        self.wallet.public_key,
                        session=self.session,
                    )
                )
            nonce = self._next_nonce
            self._next_nonce += 1
            return nonce

    async def _invalidate_reserved_nonce(self, nonce: int) -> None:
        async with self._nonce_reservation_lock:
            if self._next_nonce is not None and nonce < self._next_nonce:
                self._next_nonce = None

    @classmethod
    def _apply_chi_headroom(
        cls,
        estimated: int,
        *,
        chi_margin: float,
        min_chi_headroom: int,
    ) -> int:
        if chi_margin < 0:
            raise ValueError("chi_margin must be >= 0")
        if min_chi_headroom < 0:
            raise ValueError("min_chi_headroom must be >= 0")

        proportional = math.ceil(estimated * chi_margin)
        headroom = max(proportional, min_chi_headroom)
        return estimated + headroom

    async def send_tx(
        self,
        contract: str,
        function: str,
        kwargs: dict,
        chi: int | None = None,
        nonce: int = None,
        chain_id: str = None,
        mode: Literal["async", "checktx", "commit"] | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        chi_margin: float | None = None,
        min_chi_headroom: int | None = None,
    ) -> TransactionSubmission:
        """Send a transaction using an explicit broadcast mode."""
        mode = mode or self.config.submission.mode
        wait_for_tx = (
            self.config.submission.wait_for_tx
            if wait_for_tx is None
            else wait_for_tx
        )
        timeout_seconds = (
            self.config.submission.timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        poll_interval_seconds = (
            self.config.submission.poll_interval_seconds
            if poll_interval_seconds is None
            else poll_interval_seconds
        )
        chi_margin = (
            self.config.submission.chi_margin
            if chi_margin is None
            else chi_margin
        )
        min_chi_headroom = (
            self.config.submission.min_chi_headroom
            if min_chi_headroom is None
            else min_chi_headroom
        )

        if mode not in {"async", "checktx", "commit"}:
            raise ValueError(
                "mode must be one of: 'async', 'checktx', 'commit'"
            )

        if chain_id is None:
            await self.ensure_chain_id()
            chain_id = self.chain_id

        estimated_stamps: int | None = None
        supplied_stamps = chi
        if supplied_stamps is None:
            chi_estimate = await self.estimate_chi(
                contract,
                function,
                kwargs,
                chi_margin=chi_margin,
                min_chi_headroom=min_chi_headroom,
            )
            estimated_stamps = chi_estimate["estimated"]
            supplied_stamps = chi_estimate["suggested"]

        reserved_nonce = await self._reserve_nonce(nonce)
        payload = {
            "chain_id": chain_id,
            "contract": contract,
            "function": function,
            "kwargs": kwargs,
            "nonce": reserved_nonce,
            "sender": self.wallet.public_key,
            "chi_supplied": supplied_stamps,
        }

        tx = tr.create_tx(payload, self.wallet)

        try:

            async def _broadcast_once():
                if mode == "async":
                    return await tr.broadcast_tx_nowait_async(
                        self.node_url,
                        tx,
                        session=self.session,
                    )
                if mode == "commit":
                    return await tr.broadcast_tx_commit_async(
                        self.node_url,
                        tx,
                        session=self.session,
                    )
                return await tr.broadcast_tx_wait_async(
                    self.node_url,
                    tx,
                    session=self.session,
                )

            data = await self._retry_broadcast(_broadcast_once)
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
            "chi_supplied": supplied_stamps,
            "chi_estimated": estimated_stamps,
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
            commit_height = str(commit_result.get("height") or "0")
            result["tx_hash"] = commit_result.get("hash")
            result["accepted"] = check_tx.get("code", 1) == 0
            result["finalized"] = (
                result["accepted"]
                and deliver_tx.get("code", 1) == 0
                and commit_height != "0"
            )
            if not result["accepted"]:
                await self._invalidate_reserved_nonce(reserved_nonce)
                result["message"] = check_tx.get("log") or "CheckTx failed"
            elif not result["finalized"]:
                result["message"] = deliver_tx.get("log") or (
                    "Transaction was not finalized"
                )
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
        chi: int | None = None,
        mode: Literal["async", "checktx", "commit"] | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        chi_margin: float | None = None,
        min_chi_headroom: int | None = None,
    ) -> TransactionSubmission:
        """Send a token to a given address."""
        return await self.send_tx(
            token,
            "transfer",
            {"amount": self._coerce_amount(amount), "to": to_address},
            chi=chi,
            mode=mode,
            wait_for_tx=wait_for_tx,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            chi_margin=chi_margin,
            min_chi_headroom=min_chi_headroom,
        )

    async def simulate(
        self, contract: str, function: str, kwargs: dict
    ) -> dict:
        payload = {
            "contract": contract,
            "function": function,
            "kwargs": kwargs,
            "sender": self.wallet.public_key,
        }
        return await self._retry_read(
            lambda: tr.simulate_tx_async(
                self.node_url,
                payload,
                session=self.session,
            )
        )

    async def call(self, contract: str, function: str, kwargs: dict) -> Any:
        simulation = await self.simulate(contract, function, kwargs)
        if simulation.get("status") not in (None, 0):
            raise SimulationError(
                str(simulation.get("result") or "Simulation failed"),
                details=simulation,
            )
        result = simulation.get("result")
        if not isinstance(result, str):
            return result
        if result.startswith("0x"):
            return result
        try:
            return ast.literal_eval(result)
        except (SyntaxError, ValueError):
            normalized = self._decode_simulation_result_string(result)
            if normalized is not None:
                return normalized
            decoded = self._decode_abci_value(result, None)
            if decoded is None and result != "None":
                return result
            return decoded

    async def get_state(
        self,
        contract: str,
        variable: str,
        *keys: object,
    ) -> None | int | ContractingDecimal | dict | list | str:
        """Retrieve contract state and decode it."""
        path = f"/get/{contract}.{variable}"
        if keys:
            path = f"{path}:{':'.join(str(key) for key in keys)}"
        return await self._abci_query_value(path)

    async def get_contract(self, contract: str) -> None | str:
        """Retrieve the preferred contract source for a contract."""
        response = await tr.abci_query_async(
            self.node_url,
            f"/contract/{contract}",
            session=self.session,
        )
        byte_string = response["result"]["response"]["value"]

        if byte_string is None or byte_string == "AA==":
            return None

        return tr.decode_str(byte_string)

    async def get_contract_code(self, contract: str) -> None | str:
        """Retrieve the canonical runtime code for a contract."""
        response = await tr.abci_query_async(
            self.node_url,
            f"/contract_code/{contract}",
            session=self.session,
        )
        byte_string = response["result"]["response"]["value"]

        if byte_string is None or byte_string == "AA==":
            return None

        return tr.decode_str(byte_string)

    async def get_approved_amount(
        self,
        contract: str,
        address: str = None,
        token: str = "currency",
    ) -> int | ContractingDecimal:
        """Retrieve approved token amount for a contract."""
        address = address if address else self.wallet.public_key

        value = await self.get_state(token, "approvals", address, contract)
        return 0 if value is None else value

    async def approve(
        self,
        contract: str,
        token: str = "currency",
        amount: int | float | str | Decimal | ContractingDecimal = 999999999999,
        chi: int | None = None,
        mode: Literal["async", "checktx", "commit"] | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        chi_margin: float | None = None,
        min_chi_headroom: int | None = None,
    ) -> TransactionSubmission:
        """Approve a contract to spend a token amount."""
        return await self.send_tx(
            token,
            "approve",
            {"amount": self._coerce_amount(amount), "to": contract},
            chi=chi,
            mode=mode,
            wait_for_tx=wait_for_tx,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            chi_margin=chi_margin,
            min_chi_headroom=min_chi_headroom,
        )

    async def submit_contract(
        self,
        name: str,
        code: str | None = None,
        args: dict = None,
        deployment_artifacts: dict | None = None,
        chi: int | None = None,
        mode: Literal["async", "checktx", "commit"] | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        chi_margin: float | None = None,
        min_chi_headroom: int | None = None,
    ) -> TransactionSubmission:
        """Submit a contract to the network."""
        kwargs: dict[str, Any] = {"name": name}
        if code is not None:
            kwargs["code"] = code
        if args:
            kwargs["constructor_args"] = args
        if deployment_artifacts is not None:
            kwargs["deployment_artifacts"] = deployment_artifacts

        return await self.send_tx(
            "submission",
            "submit_contract",
            kwargs,
            chi=chi,
            mode=mode,
            wait_for_tx=wait_for_tx,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            chi_margin=chi_margin,
            min_chi_headroom=min_chi_headroom,
        )

    async def get_nodes(self) -> list[str]:
        """Retrieve the peer IPs from the network."""
        response = await self._retry_read(
            lambda: tr.request_json_async(
                "POST",
                f"{self.node_url}/net_info",
                session=self.session,
                raise_for_status=True,
            )
        )
        peers = response["result"]["peers"]
        return [peer["remote_ip"] for peer in peers]

    async def get_genesis(self) -> dict[str, Any]:
        """Retrieve genesis info from the network."""
        return await self._retry_read(
            lambda: tr.request_json_async(
                "POST",
                f"{self.node_url}/genesis",
                session=self.session,
                raise_for_status=True,
            )
        )

    async def get_chain_id(self) -> str:
        """Retrieve chain_id from the network."""
        genesis = await self.get_genesis()
        return genesis["result"]["genesis"]["chain_id"]

    async def get_node_status(self) -> NodeStatus:
        payload = await self._retry_read(
            lambda: tr.request_json_async(
                "GET",
                f"{self.node_url}/status",
                session=self.session,
                raise_for_status=True,
            )
        )
        if not isinstance(payload, dict):
            raise XianException("Unexpected node status payload")
        return NodeStatus.from_status_response(payload)

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

    async def get_developer_rewards(
        self, recipient_key: str
    ) -> DeveloperRewardSummary:
        payload = await self._abci_query_value(
            f"/developer_rewards/{recipient_key}"
        )
        if not isinstance(payload, dict):
            raise XianException("Unexpected developer rewards payload")
        return DeveloperRewardSummary.from_dict(payload)

    async def get_token_balances(
        self,
        address: str | None = None,
        *,
        limit: int = 100,
        offset: int = 0,
        include_zero: bool = False,
    ) -> TokenBalancePage:
        address = address or self.wallet.public_key
        path = f"/token_balances/{address}/limit={limit}/offset={offset}"
        if include_zero:
            path = f"{path}/include_zero=true"
        payload = await self._abci_query_value(path)
        if not isinstance(payload, dict):
            raise XianException("Unexpected token balances payload")
        return TokenBalancePage.from_dict(payload)

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
        payload: Any = None
        try:
            payload = await self._abci_query_value(f"/events_for_tx/{tx_hash}")
        except XianException:
            payload = None

        if isinstance(payload, list):
            return [IndexedEvent.from_dict(item) for item in payload]

        fallback_events = await self._graphql_get_events_for_tx(tx_hash)
        if fallback_events:
            return fallback_events
        if payload is None:
            return []
        raise XianException("Unexpected event list payload")

    async def list_shielded_output_tags(
        self,
        tag_value: str,
        *,
        kind: str = "sync_hint",
        limit: int = 100,
        offset: int = 0,
        after_id: int | None = None,
    ) -> list[ShieldedOutputTag]:
        path = f"/shielded_output_tags/{tag_value}/limit={limit}/kind={kind}"
        if after_id is not None:
            path = f"{path}/after_id={after_id}"
        else:
            path = f"{path}/offset={offset}"

        payload = await self._abci_query_value(path)
        if not isinstance(payload, dict):
            raise XianException("Unexpected shielded output tag payload")

        items = payload.get("items")
        if not isinstance(items, list):
            raise XianException("Unexpected shielded output tag item list")
        return [ShieldedOutputTag.from_dict(item) for item in items]

    async def list_shielded_wallet_history(
        self,
        tag_value: str,
        *,
        kind: str = "sync_hint",
        limit: int = 100,
        after_note_index: int = 0,
    ) -> list[ShieldedWalletHistoryEntry]:
        path = (
            f"/shielded_wallet_history/{tag_value}/limit={limit}/kind={kind}"
            f"/after_note_index={after_note_index}"
        )
        payload = await self._abci_query_value(path)
        if not isinstance(payload, dict):
            raise XianException("Unexpected shielded wallet history payload")

        items = payload.get("items")
        if not isinstance(items, list):
            raise XianException("Unexpected shielded wallet history item list")
        return [ShieldedWalletHistoryEntry.from_dict(item) for item in items]

    async def list_events(
        self,
        contract: str,
        event: str,
        *,
        limit: int = 100,
        offset: int = 0,
        after_id: int | None = None,
    ) -> list[IndexedEvent]:
        path = f"/events/{contract}/{event}/limit={limit}"
        if after_id is not None:
            path = f"{path}/after_id={after_id}"
        else:
            path = f"{path}/offset={offset}"

        payload: Any = None
        try:
            payload = await self._abci_query_value(path)
        except XianException:
            payload = None

        if isinstance(payload, list):
            return [IndexedEvent.from_dict(item) for item in payload]

        fallback_events = await self._graphql_list_events(
            contract,
            event,
            limit=limit,
            offset=offset,
            after_id=after_id,
        )
        if fallback_events:
            return fallback_events
        if payload is None:
            return []
        raise XianException("Unexpected event list payload")

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

    def contract(self, name: str) -> AsyncContractClient:
        return AsyncContractClient(self, name)

    def token(self, name: str = "currency") -> AsyncTokenClient:
        return AsyncTokenClient(self, name)

    def events(self, contract: str, event: str) -> AsyncEventClient:
        return AsyncEventClient(self, contract, event)

    def state_key(
        self,
        contract: str,
        variable: str,
        *keys: str,
    ) -> AsyncStateKeyClient:
        return AsyncStateKeyClient(self, contract, variable, tuple(keys))

    async def _get_latest_block_height(self) -> int:
        status = await self.get_node_status()
        if status.latest_block_height is None:
            raise XianException(
                "Node status did not include latest_block_height"
            )
        return status.latest_block_height

    async def _get_live_block(self, height: int) -> IndexedBlock | None:
        payload = await self._retry_read(
            lambda: tr.request_json_async(
                "GET",
                f"{self.node_url}/block?height={height}",
                session=self.session,
                raise_for_status=True,
            )
        )
        if not isinstance(payload, dict):
            raise XianException("Unexpected live block payload")

        result = payload.get("result", {})
        block = result.get("block")
        if not isinstance(block, dict):
            return None

        header = block.get("header", {})
        block_data = block.get("data", {})
        raw_height = header.get("height")
        try:
            block_height = int(raw_height) if raw_height is not None else None
        except (TypeError, ValueError):
            block_height = None

        txs = block_data.get("txs") or []
        return IndexedBlock(
            height=block_height,
            block_hash=result.get("block_id", {}).get("hash"),
            tx_count=len(txs),
            app_hash=header.get("app_hash"),
            block_time_iso=header.get("time"),
            raw=payload,
        )

    async def _receive_ws_json(
        self,
        ws: aiohttp.ClientWebSocketResponse,
    ) -> dict[str, Any]:
        while True:
            msg = await ws.receive()
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    return payload
                continue
            if msg.type == aiohttp.WSMsgType.ERROR:
                raise TransportError(
                    "CometBFT websocket error",
                    cause=ws.exception(),
                )
            if msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
            ):
                raise TransportError("CometBFT websocket closed")

    async def _subscribe_cometbft_txs(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        *,
        contract: str,
        event: str,
    ) -> list[dict[str, Any]]:
        subscription_id = "xian-py-watch-events"
        query = _build_cometbft_event_query(contract, event)
        buffered: list[dict[str, Any]] = []
        await ws.send_json(
            {
                "jsonrpc": "2.0",
                "method": "subscribe",
                "id": subscription_id,
                "params": {"query": query},
            }
        )

        while True:
            payload = await self._receive_ws_json(ws)
            if "error" in payload:
                raise XianException(
                    payload.get("error", {}).get("message")
                    or "CometBFT subscription failed",
                    details=payload,
                )
            if payload.get("id") == subscription_id:
                return buffered
            buffered.append(payload)

    @staticmethod
    def _match_indexed_event(
        candidates: list[IndexedEvent],
        live_event: LiveEvent,
    ) -> IndexedEvent | None:
        for item in candidates:
            if (
                live_event.event_index is not None
                and item.event_index == live_event.event_index
            ):
                return item
        for item in candidates:
            if (
                item.contract == live_event.contract
                and item.event == live_event.event
                and item.signer == live_event.signer
                and item.caller == live_event.caller
                and item.data == live_event.data
            ):
                return item
        return None

    async def _resolve_live_indexed_events(
        self,
        live_events: list[LiveEvent],
        *,
        poll_interval_seconds: float,
    ) -> list[IndexedEvent]:
        if not live_events:
            return []

        tx_hash = live_events[0].tx_hash
        if not tx_hash:
            raise XianException(
                "CometBFT websocket event missing tx_hash",
                details={"events": [event.raw for event in live_events]},
            )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(
            self.config.transport.read_timeout_seconds,
            1.0,
        )

        while True:
            indexed_events: list[IndexedEvent] = []
            try:
                indexed_events = await self.get_events_for_tx(tx_hash)
            except XianException:
                indexed_events = []

            resolved_events: list[IndexedEvent] = []
            missing = False
            for live_event in live_events:
                resolved = self._match_indexed_event(indexed_events, live_event)
                if resolved is None or resolved.id is None:
                    missing = True
                    break
                resolved_events.append(resolved)
            if not missing:
                return resolved_events

            remaining_seconds = deadline - loop.time()
            if remaining_seconds <= 0:
                raise XianException(
                    "CometBFT websocket events were not indexed before timeout",
                    details={"tx_hash": tx_hash},
                )
            await asyncio.sleep(
                min(
                    poll_interval_seconds,
                    remaining_seconds,
                    1.0,
                )
            )

    async def _watch_events_polling(
        self,
        contract: str,
        event: str,
        *,
        after_id: int | None = None,
        limit: int | None = None,
        poll_interval_seconds: float | None = None,
    ):
        if limit is None:
            limit = self.config.watcher.batch_limit
        if poll_interval_seconds is None:
            poll_interval_seconds = self.config.watcher.poll_interval_seconds
        if limit <= 0:
            raise ValueError("limit must be > 0")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be > 0")

        cursor = after_id if after_id is not None else 0

        while True:
            events = await self.list_events(
                contract,
                event,
                limit=limit,
                after_id=cursor,
            )
            if not events:
                await asyncio.sleep(poll_interval_seconds)
                continue

            for item in events:
                if item.id is None:
                    raise XianException(
                        "Event watcher requires event IDs in indexed payloads"
                    )
                cursor = item.id
                yield item

    async def watch_blocks(
        self,
        *,
        start_height: int | None = None,
        poll_interval_seconds: float | None = None,
    ):
        if poll_interval_seconds is None:
            poll_interval_seconds = self.config.watcher.poll_interval_seconds
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be > 0")

        next_height = start_height
        if next_height is None:
            next_height = await self._get_latest_block_height() + 1

        while True:
            latest_height = await self._get_latest_block_height()
            emitted = False
            while next_height <= latest_height:
                block = await self._get_live_block(next_height)
                if block is None:
                    break
                emitted = True
                yield block
                next_height += 1

            if not emitted:
                await asyncio.sleep(poll_interval_seconds)

    async def watch_events(
        self,
        contract: str,
        event: str,
        *,
        after_id: int | None = None,
        limit: int | None = None,
        poll_interval_seconds: float | None = None,
    ):
        watcher = self.config.watcher
        if limit is None:
            limit = watcher.batch_limit
        if poll_interval_seconds is None:
            poll_interval_seconds = watcher.poll_interval_seconds
        if limit <= 0:
            raise ValueError("limit must be > 0")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be > 0")

        mode = watcher.mode
        if mode == "poll":
            async for item in self._watch_events_polling(
                contract,
                event,
                after_id=after_id,
                limit=limit,
                poll_interval_seconds=poll_interval_seconds,
            ):
                yield item
            return

        ws_url = self._resolve_cometbft_ws_url()
        cursor = after_id if after_id is not None else 0
        websocket_started = False

        while True:
            try:
                async with self.session.ws_connect(
                    ws_url,
                    heartbeat=watcher.websocket_heartbeat_seconds,
                    receive_timeout=None,
                ) as ws:
                    buffered = await self._subscribe_cometbft_txs(
                        ws,
                        contract=contract,
                        event=event,
                    )
                    websocket_started = True

                    while True:
                        pending = await self.list_events(
                            contract,
                            event,
                            limit=limit,
                            after_id=cursor,
                        )
                        if not pending:
                            break
                        for item in pending:
                            if item.id is None:
                                raise XianException(
                                    "Event watcher requires event IDs in "
                                    "indexed payloads"
                                )
                            cursor = item.id
                            yield item

                    while True:
                        payload = (
                            buffered.pop(0)
                            if buffered
                            else await self._receive_ws_json(ws)
                        )

                        live_events = _extract_matching_live_events(
                            payload,
                            contract=contract,
                            event=event,
                        )
                        if not live_events:
                            continue

                        resolved_events = (
                            await self._resolve_live_indexed_events(
                                live_events,
                                poll_interval_seconds=poll_interval_seconds,
                            )
                        )
                        for resolved in resolved_events:
                            if resolved.id is None or resolved.id <= cursor:
                                continue
                            cursor = resolved.id
                            yield resolved
            except asyncio.CancelledError:
                raise
            except Exception:
                if not websocket_started and mode == "auto":
                    async for item in self._watch_events_polling(
                        contract,
                        event,
                        after_id=cursor,
                        limit=limit,
                        poll_interval_seconds=poll_interval_seconds,
                    ):
                        yield item
                    return
                await asyncio.sleep(poll_interval_seconds)

    async def watch_live_events(
        self,
        contract: str,
        event: str,
        *,
        poll_interval_seconds: float | None = None,
    ):
        watcher = self.config.watcher
        if poll_interval_seconds is None:
            poll_interval_seconds = watcher.poll_interval_seconds
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be > 0")

        ws_url = self._resolve_cometbft_ws_url()

        while True:
            try:
                async with self.session.ws_connect(
                    ws_url,
                    heartbeat=watcher.websocket_heartbeat_seconds,
                    receive_timeout=None,
                ) as ws:
                    buffered = await self._subscribe_cometbft_txs(
                        ws,
                        contract=contract,
                        event=event,
                    )

                    while True:
                        payload = (
                            buffered.pop(0)
                            if buffered
                            else await self._receive_ws_json(ws)
                        )
                        live_events = _extract_matching_live_events(
                            payload,
                            contract=contract,
                            event=event,
                        )
                        for live_event in live_events:
                            yield live_event
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(poll_interval_seconds)

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
    def _decode_simulation_result_string(result: str) -> Any | None:
        quoted_datetimes = _SIMULATION_DATETIME_RE.sub(
            lambda match: repr(match.group(1)),
            result,
        )
        if quoted_datetimes == result:
            return None

        try:
            return ast.literal_eval(quoted_datetimes)
        except (SyntaxError, ValueError):
            return None

    @staticmethod
    def _decode_abci_value(
        data: str,
        type_of_data: str | None,
    ) -> bool | int | ContractingDecimal | dict | list | str | None:
        if type_of_data == "int":
            try:
                return int(data)
            except (TypeError, ValueError):
                return XianAsync._decode_abci_value(data, None)
        if type_of_data == "bool":
            return data == "True"
        if type_of_data == "decimal":
            return ContractingDecimal(data)
        if type_of_data in {"dict", "list"}:
            return decode(data)
        if type_of_data == "str":
            return data

        if data == "True":
            return True
        if data == "False":
            return False
        if data == "None":
            return None

        try:
            return decode(data)
        except Exception:
            return data
