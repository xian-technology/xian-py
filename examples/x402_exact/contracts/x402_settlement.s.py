payments = Hash()

TOKEN_TRANSFER_INTERFACE = [
    importlib.Func("transfer_from", args=("amount", "to", "main_account")),
]

PaymentSettledEvent = LogEvent(
    "X402PaymentSettled",
    {
        "payment_id": indexed(str),
        "payer": indexed(str),
        "pay_to": indexed(str),
        "token_contract": str,
        "amount": (int, float, decimal),
        "resource": str,
        "facilitator": str,
    },
)


@construct
def seed():
    pass


def parse_time(value: str):
    return datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def require_token(token_contract: str):
    assert importlib.exists(token_contract), "Token contract does not exist."
    assert importlib.enforce_interface(token_contract, TOKEN_TRANSFER_INTERFACE), (
        "Token contract does not satisfy the x402 transfer interface."
    )
    return importlib.import_module(token_contract)


def field_hash(value: str):
    return hashlib.sha3_text("s:" + value)


def construct_payment_msg(
    x402_version: int,
    scheme: str,
    network: str,
    token_contract: str,
    amount_text: str,
    pay_to: str,
    resource: str,
    payer: str,
    payment_id: str,
    deadline: str,
    settlement_contract: str,
):
    return (
        "xian-x402-exact-v1:"
        + field_hash(str(x402_version))
        + ":"
        + field_hash(scheme)
        + ":"
        + field_hash(network)
        + ":"
        + field_hash(token_contract)
        + ":"
        + field_hash(amount_text)
        + ":"
        + field_hash(pay_to)
        + ":"
        + field_hash(resource)
        + ":"
        + field_hash(payer)
        + ":"
        + field_hash(payment_id)
        + ":"
        + field_hash(deadline)
        + ":"
        + field_hash(settlement_contract)
    )


@export
def settle(
    token_contract: str,
    payer: str,
    pay_to: str,
    amount: float,
    amount_text: str,
    resource: str,
    payment_id: str,
    deadline: str,
    payment_signature: str,
    permit_signature: str,
    permit_nonce: int,
    x402_version: int = 2,
    scheme: str = "exact",
    network: str = "",
    permit_authorizer_contract: str = "permit_authorizer",
    settlement_contract: str = "con_x402_settlement",
):
    assert x402_version == 2, "Unsupported x402 version."
    assert scheme == "exact", "Unsupported x402 scheme."
    assert network == "xian:" + chain_id, "Payment is for a different network."
    assert settlement_contract == ctx.this, "Wrong settlement contract."
    assert payment_id != "", "payment_id is required."
    assert payments[payment_id] is None, "Payment has already been settled."
    assert amount > 0, "Payment amount must be positive."
    assert amount_text == str(amount), "Payment amount text mismatch."

    deadline_time = parse_time(deadline)
    assert now < deadline_time, "Payment has expired."

    payment_msg = construct_payment_msg(
        x402_version=x402_version,
        scheme=scheme,
        network=network,
        token_contract=token_contract,
        amount_text=amount_text,
        pay_to=pay_to,
        resource=resource,
        payer=payer,
        payment_id=payment_id,
        deadline=str(deadline_time),
        settlement_contract=settlement_contract,
    )
    assert crypto.verify(payer, payment_msg, payment_signature), (
        "Invalid x402 payment signature."
    )

    permit_authorizer = importlib.import_module(permit_authorizer_contract)
    permit_authorizer.permit(
        token_contract=token_contract,
        owner=payer,
        spender=ctx.this,
        value=amount,
        deadline=str(deadline_time),
        nonce=permit_nonce,
        signature=permit_signature,
    )

    token = require_token(token_contract)
    token.transfer_from(amount=amount, to=pay_to, main_account=payer)

    payments[payment_id] = {
        "payer": payer,
        "pay_to": pay_to,
        "token_contract": token_contract,
        "amount": amount,
        "amount_text": amount_text,
        "resource": resource,
        "facilitator": ctx.caller,
    }

    PaymentSettledEvent(
        {
            "payment_id": payment_id,
            "payer": payer,
            "pay_to": pay_to,
            "token_contract": token_contract,
            "amount": amount,
            "resource": resource,
            "facilitator": ctx.caller,
        }
    )

    return payment_id
