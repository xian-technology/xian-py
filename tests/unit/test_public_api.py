from xian_py import (
    BdsStatus,
    PerformanceStatus,
    TransactionReceipt,
    TransactionSubmission,
    Wallet,
    Xian,
    XianAsync,
    XianException,
    run_sync,
    to_contract_time,
)


def test_public_exports_are_available() -> None:
    assert Wallet is not None
    assert Xian is not None
    assert XianAsync is not None
    assert BdsStatus is not None
    assert PerformanceStatus is not None
    assert TransactionReceipt is not None
    assert TransactionSubmission is not None
    assert XianException is not None
    assert run_sync is not None
    assert to_contract_time is not None


def test_sync_client_can_be_created_without_network_when_chain_id_is_provided() -> (
    None
):
    wallet = Wallet()
    client = Xian(
        "http://127.0.0.1:26657", chain_id="xian-test-1", wallet=wallet
    )

    assert client.chain_id == "xian-test-1"
    assert client.wallet is wallet
