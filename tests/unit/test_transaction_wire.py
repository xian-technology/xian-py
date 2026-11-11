import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from xian_runtime_types.encoding import convert_dict

from xian_py import Wallet
from xian_py.exception import TransactionError
from xian_py.transaction import canonical_json, create_tx, prepare_transaction

VECTORS = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "xian-contracting/tests/fixtures/transaction_wire.json"
    ).read_text(encoding="utf-8")
)


@pytest.mark.parametrize("typed", [False, True], ids=["raw-tags", "runtime-values"])
@pytest.mark.parametrize("vector", VECTORS["cases"], ids=lambda item: item["name"])
def test_shared_transaction_wire(vector, typed):
    wallet = Wallet(VECTORS["private_key"])
    payload = dict(vector["payload"])
    # Raw JSON is a public SDK input too; converting every fixture hides that boundary.
    if typed:
        payload["kwargs"] = convert_dict(payload["kwargs"])
    tx = create_tx(payload, wallet)
    assert canonical_json(tx["payload"]) == vector["canonical_payload"]
    assert tx["metadata"]["signature"] == vector["signature"]
    prepared = prepare_transaction(tx)
    assert prepared.json_bytes.decode() == vector["transaction_json"]
    assert prepared.submitted_bytes == vector["transaction_json"].encode().hex().encode()


@pytest.mark.parametrize("receipt", VECTORS["node_receipts"], ids=lambda item: item["name"])
def test_node_receipt_hash_matches_prepared_and_block_scan(receipt):
    import base64

    from xian_py.transaction import _hash_block_tx

    submitted = base64.b64decode(receipt["block_tx_base64"])
    signed = json.loads(bytes.fromhex(submitted.decode()).decode())
    assert prepare_transaction(signed).tx_hash == receipt["tx_hash"]
    assert _hash_block_tx(receipt["block_tx_base64"]) == receipt["tx_hash"]


@pytest.mark.parametrize(
    "vector",
    json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "xian-contracting/tests/fixtures/transaction_numeric_v2.json"
        ).read_text()
    )["cases"],
    ids=lambda item: item["name"],
)
def test_exact_numeric_profile_wire(vector):
    from decimal import Decimal

    kwargs = vector["payload"]["kwargs"]

    def native(value):
        if isinstance(value, dict) and "__fixed__" in value:
            return Decimal(value["__fixed__"])
        if isinstance(value, dict) and "__big_int__" in value:
            return int(value["__big_int__"])
        return value

    typed = {"values": [native(value) for value in kwargs["values"]]}
    for values in [typed, kwargs]:
        payload = {**vector["payload"], "kwargs": values}
        signed = create_tx(payload, Wallet(VECTORS["private_key"]), vm_profile="xian_vm_v2")
        assert prepare_transaction(signed).json_bytes.decode() == vector["transaction_json"]


@pytest.mark.parametrize("field", ["nonce", "chi_supplied"])
def test_v2_envelope_uses_bare_safe_integers_before_calling_signer(field):
    wallet = Wallet(VECTORS["private_key"])
    unsigned = {**VECTORS["cases"][0]["payload"], "kwargs": {"amount": 2**53}}
    tx = create_tx({**unsigned, field: 2**53 - 1}, wallet, vm_profile="xian_vm_v2")
    assert type(tx["payload"][field]) is int
    assert tx["payload"][field] == 2**53 - 1
    assert tx["payload"]["kwargs"]["amount"] == {"__big_int__": str(2**53)}

    signer = Mock(spec=wallet)
    for invalid in (2**53, {"__big_int__": str(2**53)}, True, -1):
        with pytest.raises(TransactionError):
            create_tx({**unsigned, field: invalid}, signer, vm_profile="xian_vm_v2")
    signer.sign_msg.assert_not_called()
    legacy = create_tx({**unsigned, field: 2**53}, wallet, vm_profile="xian_vm_v1")
    assert legacy["payload"][field] == 2**53
