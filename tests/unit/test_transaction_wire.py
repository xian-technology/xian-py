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


@pytest.mark.parametrize("vector", VECTORS["cases"], ids=lambda item: item["name"])
def test_shared_transaction_wire(vector):
    wallet = Wallet(VECTORS["private_key"])
    payload = dict(vector["payload"])
    # Exercise normalization of actual runtime values, including nested wrappers.
    payload["kwargs"] = convert_dict(payload["kwargs"])
    tx = create_tx(payload, wallet)
    assert canonical_json(tx["payload"]) == vector["canonical_payload"]
    assert tx["metadata"]["signature"] == vector["signature"]
    prepared = prepare_transaction(tx)
    assert prepared.json_bytes.decode() == vector["transaction_json"]
    assert prepared.submitted_bytes == vector["transaction_json"].encode().hex().encode()
