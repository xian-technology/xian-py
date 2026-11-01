import json
from pathlib import Path

import pytest
from xian_runtime_types.encoding import convert_dict

from xian_py import Wallet
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
