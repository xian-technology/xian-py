from decimal import Decimal

from xian_runtime_types.decimal import ContractingDecimal

from xian_py.encoding import decode, encode
from xian_py.xian_datetime import Datetime


def test_encode_decode_round_trip_preserves_supported_types() -> None:
    payload = {
        "bytes": b"\x01\x02",
        "big_int": 2**80,
        "decimal": ContractingDecimal("1.25"),
        "datetime": Datetime(2026, 3, 13, 10, 30, 0),
        "plain_decimal": Decimal("2.5"),
    }

    decoded = decode(encode(payload))

    assert decoded["bytes"] == payload["bytes"]
    assert decoded["big_int"] == payload["big_int"]
    assert str(decoded["decimal"]) == "1.25"
    assert str(decoded["plain_decimal"]) == "2.5"
    assert decoded["datetime"].year == 2026
    assert decoded["datetime"].minute == 30
