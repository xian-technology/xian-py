from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xian_runtime_types.decimal import ContractingDecimal

from xian_py.models import (
    IndexedEvent,
    StateEntry,
    TransactionSubmission,
)


def _merge_call_kwargs(
    kwargs: dict[str, Any] | None,
    extra_kwargs: dict[str, Any],
) -> dict[str, Any]:
    if kwargs is None:
        return dict(extra_kwargs)
    if extra_kwargs:
        merged = dict(kwargs)
        merged.update(extra_kwargs)
        return merged
    return dict(kwargs)


@dataclass(frozen=True)
class AsyncEventClient:
    client: Any
    contract: str
    event: str

    async def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        after_id: int | None = None,
    ) -> list[IndexedEvent]:
        return await self.client.list_events(
            self.contract,
            self.event,
            limit=limit,
            offset=offset,
            after_id=after_id,
        )

    async def watch(
        self,
        *,
        after_id: int | None = None,
        limit: int | None = None,
        poll_interval_seconds: float | None = None,
    ):
        async for item in self.client.watch_events(
            self.contract,
            self.event,
            after_id=after_id,
            limit=limit,
            poll_interval_seconds=poll_interval_seconds,
        ):
            yield item

    async def watch_live(
        self,
        *,
        poll_interval_seconds: float | None = None,
    ):
        async for item in self.client.watch_live_events(
            self.contract,
            self.event,
            poll_interval_seconds=poll_interval_seconds,
        ):
            yield item


@dataclass(frozen=True)
class EventClient:
    client: Any
    contract: str
    event: str

    def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        after_id: int | None = None,
    ) -> list[IndexedEvent]:
        return self.client.list_events(
            self.contract,
            self.event,
            limit=limit,
            offset=offset,
            after_id=after_id,
        )

    def watch(
        self,
        *,
        after_id: int | None = None,
        limit: int | None = None,
        poll_interval_seconds: float | None = None,
    ):
        return self.client.watch_events(
            self.contract,
            self.event,
            after_id=after_id,
            limit=limit,
            poll_interval_seconds=poll_interval_seconds,
        )

    def watch_live(
        self,
        *,
        poll_interval_seconds: float | None = None,
    ):
        return self.client.watch_live_events(
            self.contract,
            self.event,
            poll_interval_seconds=poll_interval_seconds,
        )


@dataclass(frozen=True)
class AsyncStateKeyClient:
    client: Any
    contract: str
    variable: str
    keys: tuple[str, ...]

    @property
    def full_key(self) -> str:
        suffix = f":{':'.join(self.keys)}" if self.keys else ""
        return f"{self.contract}.{self.variable}{suffix}"

    async def get(self) -> Any:
        return await self.client.get_state(
            self.contract, self.variable, *self.keys
        )

    async def history(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StateEntry]:
        return await self.client.get_state_history(
            self.full_key,
            limit=limit,
            offset=offset,
        )


@dataclass(frozen=True)
class StateKeyClient:
    client: Any
    contract: str
    variable: str
    keys: tuple[str, ...]

    @property
    def full_key(self) -> str:
        suffix = f":{':'.join(self.keys)}" if self.keys else ""
        return f"{self.contract}.{self.variable}{suffix}"

    def get(self) -> Any:
        return self.client.get_state(self.contract, self.variable, *self.keys)

    def history(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StateEntry]:
        return self.client.get_state_history(
            self.full_key,
            limit=limit,
            offset=offset,
        )


@dataclass(frozen=True)
class AsyncContractClient:
    client: Any
    name: str

    async def get_state(self, variable: str, *keys: str) -> Any:
        return await self.client.get_state(self.name, variable, *keys)

    def state_key(self, variable: str, *keys: str) -> AsyncStateKeyClient:
        return AsyncStateKeyClient(
            self.client, self.name, variable, tuple(keys)
        )

    async def simulate(
        self,
        function: str,
        *,
        kwargs: dict[str, Any] | None = None,
        **contract_kwargs: Any,
    ) -> dict[str, Any]:
        return await self.client.simulate(
            self.name,
            function,
            _merge_call_kwargs(kwargs, contract_kwargs),
        )

    async def call(
        self,
        function: str,
        *,
        kwargs: dict[str, Any] | None = None,
        **contract_kwargs: Any,
    ) -> Any:
        return await self.client.call(
            self.name,
            function,
            _merge_call_kwargs(kwargs, contract_kwargs),
        )

    async def send(
        self,
        function: str,
        *,
        kwargs: dict[str, Any] | None = None,
        stamps: int | None = None,
        nonce: int | None = None,
        chain_id: str | None = None,
        mode: str | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        stamp_margin: float | None = None,
        min_stamp_headroom: int | None = None,
        **contract_kwargs: Any,
    ) -> TransactionSubmission:
        return await self.client.send_tx(
            contract=self.name,
            function=function,
            kwargs=_merge_call_kwargs(kwargs, contract_kwargs),
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

    async def get_source(self) -> str | None:
        return await self.client.get_contract(self.name)

    async def get_code(self) -> str | None:
        return await self.client.get_contract_code(self.name)

    def events(self, event: str) -> AsyncEventClient:
        return AsyncEventClient(self.client, self.name, event)


@dataclass(frozen=True)
class ContractClient:
    client: Any
    name: str

    def get_state(self, variable: str, *keys: str) -> Any:
        return self.client.get_state(self.name, variable, *keys)

    def state_key(self, variable: str, *keys: str) -> StateKeyClient:
        return StateKeyClient(self.client, self.name, variable, tuple(keys))

    def simulate(
        self,
        function: str,
        *,
        kwargs: dict[str, Any] | None = None,
        **contract_kwargs: Any,
    ) -> dict[str, Any]:
        return self.client.simulate(
            self.name,
            function,
            _merge_call_kwargs(kwargs, contract_kwargs),
        )

    def call(
        self,
        function: str,
        *,
        kwargs: dict[str, Any] | None = None,
        **contract_kwargs: Any,
    ) -> Any:
        return self.client.call(
            self.name,
            function,
            _merge_call_kwargs(kwargs, contract_kwargs),
        )

    def send(
        self,
        function: str,
        *,
        kwargs: dict[str, Any] | None = None,
        stamps: int | None = None,
        nonce: int | None = None,
        chain_id: str | None = None,
        mode: str | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        stamp_margin: float | None = None,
        min_stamp_headroom: int | None = None,
        **contract_kwargs: Any,
    ) -> TransactionSubmission:
        return self.client.send_tx(
            contract=self.name,
            function=function,
            kwargs=_merge_call_kwargs(kwargs, contract_kwargs),
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

    def get_source(self) -> str | None:
        return self.client.get_contract(self.name)

    def get_code(self) -> str | None:
        return self.client.get_contract_code(self.name)

    def events(self, event: str) -> EventClient:
        return EventClient(self.client, self.name, event)


@dataclass(frozen=True)
class AsyncTokenClient(AsyncContractClient):
    async def balance_of(
        self,
        address: str | None = None,
    ) -> int | ContractingDecimal:
        return await self.client.get_balance(
            address=address, contract=self.name
        )

    async def transfer(
        self,
        to_address: str,
        amount: int | float | str | ContractingDecimal,
        *,
        stamps: int | None = None,
        mode: str | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        stamp_margin: float | None = None,
        min_stamp_headroom: int | None = None,
    ) -> TransactionSubmission:
        return await self.client.send(
            amount=amount,
            to_address=to_address,
            token=self.name,
            stamps=stamps,
            mode=mode,
            wait_for_tx=wait_for_tx,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            stamp_margin=stamp_margin,
            min_stamp_headroom=min_stamp_headroom,
        )

    async def approve(
        self,
        spender: str,
        *,
        amount: int | float | str | ContractingDecimal = 999999999999,
        stamps: int | None = None,
        mode: str | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        stamp_margin: float | None = None,
        min_stamp_headroom: int | None = None,
    ) -> TransactionSubmission:
        return await self.client.approve(
            contract=spender,
            token=self.name,
            amount=amount,
            stamps=stamps,
            mode=mode,
            wait_for_tx=wait_for_tx,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            stamp_margin=stamp_margin,
            min_stamp_headroom=min_stamp_headroom,
        )

    async def allowance(
        self,
        spender: str,
        *,
        owner: str | None = None,
    ) -> int | ContractingDecimal:
        value = await self.client.get_state(
            self.name,
            "approvals",
            owner or self.client.wallet.public_key,
            spender,
        )
        return 0 if value is None else value

    def transfers(self) -> AsyncEventClient:
        return self.events("Transfer")


@dataclass(frozen=True)
class TokenClient(ContractClient):
    def balance_of(
        self,
        address: str | None = None,
    ) -> int | ContractingDecimal:
        return self.client.get_balance(address=address, contract=self.name)

    def transfer(
        self,
        to_address: str,
        amount: int | float | str | ContractingDecimal,
        *,
        stamps: int | None = None,
        mode: str | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        stamp_margin: float | None = None,
        min_stamp_headroom: int | None = None,
    ) -> TransactionSubmission:
        return self.client.send(
            amount=amount,
            to_address=to_address,
            token=self.name,
            stamps=stamps,
            mode=mode,
            wait_for_tx=wait_for_tx,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            stamp_margin=stamp_margin,
            min_stamp_headroom=min_stamp_headroom,
        )

    def approve(
        self,
        spender: str,
        *,
        amount: int | float | str | ContractingDecimal = 999999999999,
        stamps: int | None = None,
        mode: str | None = None,
        wait_for_tx: bool | None = None,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        stamp_margin: float | None = None,
        min_stamp_headroom: int | None = None,
    ) -> TransactionSubmission:
        return self.client.approve(
            contract=spender,
            token=self.name,
            amount=amount,
            stamps=stamps,
            mode=mode,
            wait_for_tx=wait_for_tx,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            stamp_margin=stamp_margin,
            min_stamp_headroom=min_stamp_headroom,
        )

    def allowance(
        self,
        spender: str,
        *,
        owner: str | None = None,
    ) -> int | ContractingDecimal:
        value = self.client.get_state(
            self.name,
            "approvals",
            owner or self.client.wallet.public_key,
            spender,
        )
        return 0 if value is None else value

    def transfers(self) -> EventClient:
        return self.events("Transfer")
