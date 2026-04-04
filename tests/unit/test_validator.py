from xian_py.validator import validate_contract

VALID_CONTRACT = """
balances = Hash()
approvals = Hash()
metadata = Hash()
operator = Variable()

@construct
def seed():
    metadata["token_name"] = "Token"
    metadata["token_symbol"] = "TKN"
    metadata["token_logo_url"] = "https://example.invalid/logo.png"
    metadata["token_website"] = "https://example.invalid"
    metadata["total_supply"] = 0
    operator.set(ctx.caller)

@export
def change_metadata(key, value):
    metadata[key] = value

@export
def transfer(amount, to):
    balances[to] += amount

@export
def approve(amount, to):
    approvals[ctx.caller, to] = amount

@export
def transfer_from(amount, to, main_account):
    assert approvals[main_account, ctx.caller] >= amount
    approvals[main_account, ctx.caller] -= amount
    balances[main_account] -= amount
    balances[to] += amount

@export
def balance_of(address):
    return balances[address]
"""

LEGACY_CONTRACT = """
balances = Hash()
metadata = Hash()

@construct
def seed():
    metadata["token_name"] = "Token"
    metadata["token_symbol"] = "TKN"
    metadata["token_logo_url"] = "https://example.invalid/logo.png"
    metadata["token_website"] = "https://example.invalid"
    metadata["operator"] = ctx.caller

@export
def change_metadata(key, value):
    metadata[key] = value

@export
def transfer(amount, to):
    balances[to] += amount

@export
def approve(amount, to):
    balances[ctx.caller, to] = amount

@export
def transfer_from(amount, to, main_account):
    balances[main_account, ctx.caller] -= amount
    balances[main_account] -= amount
    balances[to] += amount

@export
def balance_of(account):
    return balances[account]
"""

WRONG_ORDER_CONTRACT = """
balances = Hash()
approvals = Hash()
metadata = Hash()

@construct
def seed():
    metadata["token_name"] = "Token"
    metadata["token_symbol"] = "TKN"
    metadata["token_logo_url"] = "https://example.invalid/logo.png"
    metadata["token_website"] = "https://example.invalid"

@export
def change_metadata(key, value):
    metadata[key] = value

@export
def transfer(amount, to):
    balances[to] += amount

@export
def approve(amount, to):
    approvals[ctx.caller, to] = amount

@export
def transfer_from(amount, main_account, to):
    approvals[main_account, ctx.caller] -= amount
    balances[main_account] -= amount
    balances[to] += amount

@export
def balance_of(address):
    return balances[address]
"""


def test_validate_contract_accepts_minimal_xsc001_shape() -> None:
    is_valid, errors = validate_contract(VALID_CONTRACT)

    assert is_valid is True
    assert errors == []


def test_validate_contract_rejects_legacy_shape() -> None:
    is_valid, errors = validate_contract(LEGACY_CONTRACT)

    assert is_valid is False
    assert any("Missing required variables" in error for error in errors)
    assert any(
        "balance_of has incorrect arguments" in error for error in errors
    )


def test_validate_contract_rejects_wrong_argument_order() -> None:
    is_valid, errors = validate_contract(WRONG_ORDER_CONTRACT)

    assert is_valid is False
    assert any(
        "transfer_from has incorrect arguments" in error for error in errors
    )


def test_validate_contract_rejects_invalid_contract() -> None:
    is_valid, errors = validate_contract("def broken(:\n")

    assert is_valid is False
    assert errors
