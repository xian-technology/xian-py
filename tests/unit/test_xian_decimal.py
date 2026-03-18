from decimal import Decimal

from xian_py.xian_decimal import MAX_DECIMAL, ContractingDecimal, fix_precision


def test_negative_nonzero_decimal_is_truthy() -> None:
    assert bool(ContractingDecimal("-1")) is True


def test_fix_precision_clamps_negative_overflow() -> None:
    value = Decimal(
        "-12345678901234567890123456789012345678901234567890123456789012"
    )
    assert fix_precision(value) == -MAX_DECIMAL


def test_fix_precision_rounds_negative_toward_zero() -> None:
    value = Decimal("-1.123456789012345678901234567890123")
    expected = Decimal("-1.12345678901234567890123456789")
    assert fix_precision(value) == expected


def test_max_decimal_exceeds_ethereum_18_decimal_range() -> None:
    ethereum_style_max = Decimal(2**256 - 1) / (Decimal(10) ** 18)
    assert MAX_DECIMAL > ethereum_style_max
