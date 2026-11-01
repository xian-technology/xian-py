"""Transaction wire inputs accept existing runtime tags without changing state policy."""

import asyncio
import base64
import json
from copy import deepcopy
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from xian_runtime_types.collections import ContractingFrozenSet, ContractingSet
from xian_runtime_types.encoding import convert_dict
from xian_runtime_types.time import Datetime, Timedelta

from xian_py import Wallet
from xian_py.transaction import (
    canonical_json,
    create_tx,
    normalize_transaction_payload,
    prepare_transaction,
    simulate_tx_async,
)

RAW_VALUES = [
    {"__time__": [2026, 11, 1, 14, 47, 2, 123456]},
    {"__delta__": [2, 3]},
    {"__fixed__": "1.2300"},
    {"__bytes__": "00ff"},
    {"__bytearray__": "00ff"},
    {"__big_int__": "1208925819614629174706176"},
    {"__set__": [1, 2]},
    {"__frozenset__": [1, 2]},
    {"__set__": {"codec": "xian-set-1", "items": [["raw_decimal", 0, "12300", -4]]}},
    {"__frozenset__": {"codec": "xian-set-1", "items": [["tuple", [["int", "1"], ["str", "a"]]]]}},
]


def payload(kwargs):
    return {
        "chain_id": "xian-local-1",
        "chi_supplied": 100,
        "contract": "con_probe",
        "function": "run",
        "kwargs": kwargs,
        "nonce": 7,
        "sender": Wallet("01" * 32).public_key,
    }


@pytest.mark.parametrize("value", RAW_VALUES)
def test_raw_tag_kwargs_preserve_signed_bytes_and_input(value):
    original = payload({"data": [[deepcopy(value)]]})
    before = deepcopy(original)
    wallet = Wallet("01" * 32)
    tx = create_tx(original, wallet)
    expected_payload = json.dumps(before, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert canonical_json(tx["payload"]) == expected_payload
    assert wallet.verify_msg(expected_payload, tx["metadata"]["signature"])
    prepared = prepare_transaction(tx)
    assert prepared.json_bytes == canonical_json(tx).encode()
    assert prepared.submitted_bytes == prepared.json_bytes.hex().encode("ascii")
    assert original == before
    assert normalize_transaction_payload(tx["payload"]) == tx["payload"]


@pytest.mark.parametrize(
    "value, wire",
    [
        (Datetime(2026, 11, 1, 14, 47, 2, 123456), RAW_VALUES[0]),
        (Timedelta(days=2, seconds=3), RAW_VALUES[1]),
        (b"\x00\xff", RAW_VALUES[3]),
        (bytearray(b"\x00\xff"), RAW_VALUES[4]),
        (2**80, RAW_VALUES[5]),
        (ContractingSet([Decimal("1.2300")]), RAW_VALUES[8]),
        (ContractingFrozenSet([(1, "a")]), RAW_VALUES[9]),
    ],
)
def test_typed_and_raw_inputs_produce_same_signature_and_round_trip(value, wire):
    wallet = Wallet("01" * 32)
    typed = create_tx(payload({"data": value}), wallet)
    raw = create_tx(payload({"data": wire}), wallet)
    assert typed == raw
    restored = convert_dict(raw["payload"]["kwargs"])["data"]
    assert restored == value
    if isinstance(value, ContractingSet):
        assert next(iter(restored)).as_tuple() == Decimal("1.2300").as_tuple()


def test_simulation_sends_raw_and_typed_kwargs_without_loss():
    original = payload(
        {"deadline": deepcopy(RAW_VALUES[0]), "amount": RAW_VALUES[2], "raw": b"abc"}
    )
    before = deepcopy(original)
    response = {
        "result": {"response": {"code": 0, "value": base64.b64encode(b'{"chi_used":1}').decode()}}
    }
    query = AsyncMock(return_value=response)
    with patch("xian_py.transaction.abci_query_async", query):
        assert asyncio.run(simulate_tx_async("http://node", original)) == {"chi_used": 1}
    path = query.await_args.args[1]
    actual_bytes = bytes.fromhex(path.removeprefix("/simulate_tx/"))
    expected = deepcopy(before)
    expected["kwargs"]["raw"] = {"__bytes__": "616263"}
    assert actual_bytes == json.dumps(expected, separators=(",", ":")).encode()
    assert original == before


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("NaN"), Decimal("Infinity")])
@pytest.mark.parametrize("simulate", [False, True])
def test_nonfinite_values_rejected_before_signing_or_simulation(value, simulate):
    original = payload({"data": [value]})
    query = AsyncMock()
    with (
        patch("xian_py.transaction.abci_query_async", query),
        pytest.raises(ValueError, match="finite"),
    ):
        if simulate:
            asyncio.run(simulate_tx_async("http://node", original))
        else:
            create_tx(original, Wallet("01" * 32))
    query.assert_not_awaited()


@pytest.mark.parametrize("simulate", [False, True])
def test_excessive_wire_depth_is_bounded(simulate):
    value = 1
    for _ in range(130):
        value = [value]
    original = payload({"data": value})
    with pytest.raises(ValueError, match="traversal limit"):
        if simulate:
            asyncio.run(simulate_tx_async("http://node", original))
        else:
            create_tx(original, Wallet("01" * 32))


def test_cyclic_kwargs_fail_before_recursive_formatting():
    value = []
    value.append(value)
    with pytest.raises(ValueError, match="cyclic"):
        create_tx(payload({"data": value}), Wallet("01" * 32))
    assert value[0] is value


def test_nonstring_nested_dictionary_key_remains_invalid():
    with pytest.raises(TypeError, match="keys"):
        create_tx(payload({"data": {1: "invalid"}}), Wallet("01" * 32))
