from decimal import Decimal

from xian_runtime_types.decimal import (
    MAX_DECIMAL,
    ContractingDecimal,
    DecimalOverflowError,
    fix_precision,
)


def test_negative_nonzero_decimal_is_truthy() -> None:
    assert bool(ContractingDecimal("-1")) is True


def test_fix_precision_rejects_negative_overflow() -> None:
    value = Decimal(
        "-12345678901234567890123456789012345678901234567890123456789012"
    )
    try:
        fix_precision(value)
    except DecimalOverflowError:
        pass
    else:
        raise AssertionError("expected DecimalOverflowError")


def test_fix_precision_rejects_positive_overflow() -> None:
    value = Decimal(
        "12345678901234567890123456789012345678901234567890123456789012"
    )
    try:
        fix_precision(value)
    except DecimalOverflowError:
        pass
    else:
        raise AssertionError("expected DecimalOverflowError")


def test_fix_precision_rounds_negative_toward_zero() -> None:
    value = Decimal("-1.123456789012345678901234567890123")
    expected = Decimal("-1.12345678901234567890123456789")
    assert fix_precision(value) == expected


def test_max_decimal_exceeds_ethereum_18_decimal_range() -> None:
    ethereum_style_max = Decimal(2**256 - 1) / (Decimal(10) ** 18)
    assert MAX_DECIMAL > ethereum_style_max


def test_fix_precision_allows_extra_fractional_digits_if_value_stays_in_range() -> (
    None
):
    value = Decimal("9" * 61 + "." + "9" * 30 + "9")
    assert fix_precision(value) == MAX_DECIMAL
