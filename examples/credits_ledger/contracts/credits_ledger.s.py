balances = Hash(default_value=0)
approvals = Hash(default_value=0)
metadata = Hash()
issuers = Hash(default_value=False)
operator = Variable()

TransferEvent = LogEvent(
    "Transfer",
    {
        "from": {"type": str, "idx": True},
        "to": {"type": str, "idx": True},
        "amount": {"type": (int, float, decimal)},
    },
)

ApproveEvent = LogEvent(
    "Approve",
    {
        "from": {"type": str, "idx": True},
        "to": {"type": str, "idx": True},
        "amount": {"type": (int, float, decimal)},
    },
)

IssueEvent = LogEvent(
    "Issue",
    {
        "to": {"type": str, "idx": True},
        "amount": {"type": (int, float, decimal)},
        "issuer": {"type": str, "idx": True},
    },
)

BurnEvent = LogEvent(
    "Burn",
    {
        "from": {"type": str, "idx": True},
        "amount": {"type": (int, float, decimal)},
        "actor": {"type": str, "idx": True},
    },
)

IssuerAddedEvent = LogEvent(
    "IssuerAdded",
    {
        "account": {"type": str, "idx": True},
        "actor": {"type": str, "idx": True},
    },
)

IssuerRemovedEvent = LogEvent(
    "IssuerRemoved",
    {
        "account": {"type": str, "idx": True},
        "actor": {"type": str, "idx": True},
    },
)


@construct
def seed(
    name: str = "Credits Ledger",
    symbol: str = "CRED",
    operator_address: str = None,
    token_logo_url: str = "",
    token_logo_svg: str = "",
    token_website: str = "",
):
    resolved_operator = operator_address or ctx.caller
    operator.set(resolved_operator)
    metadata["name"] = name
    metadata["symbol"] = symbol
    metadata["token_name"] = name
    metadata["token_symbol"] = symbol
    metadata["token_logo_url"] = token_logo_url
    metadata["token_logo_svg"] = token_logo_svg
    metadata["token_website"] = token_website
    metadata["operator"] = resolved_operator
    metadata["total_supply"] = 0
    issuers[resolved_operator] = True


def require_operator():
    assert ctx.caller == operator.get(), "Only operator can manage issuers."


def require_issuer():
    assert issuers[ctx.caller], "Only issuer can mint or burn on behalf of others."


@export
def set_operator(account: str):
    require_operator()
    operator.set(account)
    metadata["operator"] = account
    issuers[account] = True


@export
def change_metadata(key: str, value: Any):
    require_operator()
    assert key != "total_supply", "total_supply is managed by the contract."
    metadata[key] = value


@export
def add_issuer(account: str):
    require_operator()
    issuers[account] = True
    IssuerAddedEvent({"account": account, "actor": ctx.caller})


@export
def remove_issuer(account: str):
    require_operator()
    assert account != metadata["operator"], "Operator must remain an issuer."
    issuers[account] = False
    IssuerRemovedEvent({"account": account, "actor": ctx.caller})


@export
def issue(to: str, amount: float):
    require_issuer()
    assert amount > 0, "Amount must be positive."
    balances[to] += amount
    metadata["total_supply"] += amount
    IssueEvent({"to": to, "amount": amount, "issuer": ctx.caller})


@export
def transfer(amount: float, to: str):
    assert amount > 0, "Amount must be positive."
    assert balances[ctx.caller] >= amount, "Insufficient balance."
    balances[ctx.caller] -= amount
    balances[to] += amount
    TransferEvent({"from": ctx.caller, "to": to, "amount": amount})


@export
def approve(amount: float, to: str):
    assert amount >= 0, "Cannot approve negative balances."
    approvals[ctx.caller, to] = amount
    ApproveEvent({"from": ctx.caller, "to": to, "amount": amount})


@export
def transfer_from(amount: float, to: str, main_account: str):
    assert amount > 0, "Amount must be positive."
    assert approvals[main_account, ctx.caller] >= amount, "Insufficient approved balance."
    assert balances[main_account] >= amount, "Insufficient balance."
    approvals[main_account, ctx.caller] -= amount
    balances[main_account] -= amount
    balances[to] += amount
    TransferEvent({"from": main_account, "to": to, "amount": amount})


@export
def burn(amount: float):
    assert amount > 0, "Amount must be positive."
    assert balances[ctx.caller] >= amount, "Insufficient balance."
    balances[ctx.caller] -= amount
    metadata["total_supply"] -= amount
    BurnEvent({"from": ctx.caller, "amount": amount, "actor": ctx.caller})


@export
def burn_from(account: str, amount: float):
    require_issuer()
    assert amount > 0, "Amount must be positive."
    assert balances[account] >= amount, "Insufficient balance."
    balances[account] -= amount
    metadata["total_supply"] -= amount
    BurnEvent({"from": account, "amount": amount, "actor": ctx.caller})


@export
def balance_of(address: str):
    return balances[address]


@export
def total_supply():
    return metadata["total_supply"]


@export
def is_issuer(account: str):
    return issuers[account]
