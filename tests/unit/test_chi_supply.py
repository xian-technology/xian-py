import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import xian_py.transaction as tr
from xian_py import (
    CHI_ESTIMATE_MARGIN,
    MAX_TX_CHI,
    TransactionError,
    Wallet,
    XianAsync,
    chi_to_supply,
)


def test_chi_to_supply_adds_the_fixed_margin_to_the_estimate() -> None:
    assert CHI_ESTIMATE_MARGIN == 2
    assert chi_to_supply(255) == 257
    assert chi_to_supply(0) == 2


def test_chi_to_supply_never_exceeds_the_per_transaction_cap() -> None:
    assert MAX_TX_CHI == 200_000
    assert chi_to_supply(MAX_TX_CHI - 3) == MAX_TX_CHI - 1
    assert chi_to_supply(MAX_TX_CHI - 2) == MAX_TX_CHI
    assert chi_to_supply(MAX_TX_CHI - 1) == MAX_TX_CHI
    assert chi_to_supply(MAX_TX_CHI) == MAX_TX_CHI


def test_chi_to_supply_refuses_an_estimate_above_the_cap() -> None:
    with pytest.raises(TransactionError, match="200001 chi exceeds .* 200000 chi"):
        chi_to_supply(MAX_TX_CHI + 1)


def _send(client: XianAsync, simulation: dict, **send_options) -> tuple:
    async def run():
        try:
            return await client.send_tx("currency", "transfer", {"amount": 1}, **send_options)
        finally:
            await client.close()

    with patch.object(tr, "get_nonce_async", AsyncMock(return_value=3)) as get_nonce:
        with patch.object(tr, "simulate_tx_async", AsyncMock(return_value=simulation)) as simulate:
            with patch.object(tr, "create_tx", return_value={"signed": True}) as create_tx:
                with patch.object(
                    tr,
                    "broadcast_tx_wait_async",
                    AsyncMock(return_value={"result": {"code": 0, "hash": "abc"}}),
                ):
                    result = asyncio.run(run())
    return result, simulate, create_tx, get_nonce


def test_send_tx_supplies_the_estimate_plus_the_margin() -> None:
    client = XianAsync("http://node", chain_id="xian-local-1", wallet=Wallet())

    result, _, create_tx, _ = _send(client, {"chi_used": 255, "status": 0})

    assert create_tx.call_args.args[0]["chi_supplied"] == 257
    assert result.chi_estimated == 255
    assert result.chi_supplied == 257


def test_send_tx_keeps_an_explicit_chi_untouched() -> None:
    client = XianAsync("http://node", chain_id="xian-local-1", wallet=Wallet())

    result, simulate, create_tx, _ = _send(client, {"chi_used": 255, "status": 0}, chi=255)

    simulate.assert_not_awaited()
    assert create_tx.call_args.args[0]["chi_supplied"] == 255
    assert result.chi_estimated is None
    assert result.chi_supplied == 255


def test_send_tx_refuses_an_estimate_above_the_cap_before_reserving_a_nonce() -> None:
    client = XianAsync("http://node", chain_id="xian-local-1", wallet=Wallet())
    get_nonce = AsyncMock(return_value=3)

    async def run():
        try:
            return await client.send_tx("currency", "transfer", {"amount": 1})
        finally:
            await client.close()

    simulation = {"chi_used": MAX_TX_CHI + 1, "status": 0}
    with patch.object(tr, "get_nonce_async", get_nonce):
        with patch.object(tr, "simulate_tx_async", AsyncMock(return_value=simulation)):
            with pytest.raises(TransactionError, match="exceeds"):
                asyncio.run(run())

    get_nonce.assert_not_awaited()
