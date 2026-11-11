import pytest

from xian_py import (
    BdsStatus,
    DeveloperRewardSummary,
    DexCandle,
    EventProjector,
    EventSource,
    LiveEvent,
    PerformanceStatus,
    ShieldedRelayerAsyncClient,
    ShieldedRelayerAsyncPoolClient,
    ShieldedRelayerCatalogEntry,
    ShieldedRelayerClient,
    ShieldedRelayerInfo,
    ShieldedRelayerInfoResult,
    ShieldedRelayerJob,
    ShieldedRelayerJobResult,
    ShieldedRelayerPoolClient,
    ShieldedRelayerQuote,
    ShieldedRelayerQuoteResult,
    SQLiteProjectionState,
    TransactionReceipt,
    TransactionSubmission,
    Wallet,
    Xian,
    XianAsync,
    XianException,
    XianX402PaymentExpectation,
    XianX402PaymentRequirement,
    merged_event_payload,
    run_sync,
    to_contract_time,
)


def test_optional_compiler_extra_defaults_to_exact_v2_artifacts() -> None:
    pytest.importorskip("contracting")
    import xian_compiler_core
    from contracting.artifacts import build_contract_artifacts

    amount = "9007199254740993.000000000000000000000000000001"
    source = f"@export\ndef amount():\n    return {amount}\n"
    artifact = build_contract_artifacts(module_name="con_amount", source=source)
    assert artifact["vm_profile"] == "xian_vm_v2"
    assert amount in artifact["vm_ir_json"]
    assert xian_compiler_core.compile_contract_artifact("con_amount", source) == artifact


def test_public_exports_are_available() -> None:
    assert Wallet is not None
    assert Xian is not None
    assert XianAsync is not None
    assert BdsStatus is not None
    assert DexCandle is not None
    assert DeveloperRewardSummary is not None
    assert EventProjector is not None
    assert EventSource is not None
    assert LiveEvent is not None
    assert PerformanceStatus is not None
    assert ShieldedRelayerAsyncClient is not None
    assert ShieldedRelayerAsyncPoolClient is not None
    assert ShieldedRelayerCatalogEntry is not None
    assert ShieldedRelayerClient is not None
    assert ShieldedRelayerInfo is not None
    assert ShieldedRelayerInfoResult is not None
    assert ShieldedRelayerJob is not None
    assert ShieldedRelayerJobResult is not None
    assert ShieldedRelayerPoolClient is not None
    assert ShieldedRelayerQuote is not None
    assert ShieldedRelayerQuoteResult is not None
    assert SQLiteProjectionState is not None
    assert TransactionReceipt is not None
    assert TransactionSubmission is not None
    assert XianException is not None
    assert XianX402PaymentExpectation is not None
    assert XianX402PaymentRequirement is not None
    assert merged_event_payload is not None
    assert run_sync is not None
    assert to_contract_time is not None


def test_sync_client_can_be_created_without_network_when_chain_id_is_provided() -> None:
    wallet = Wallet()
    client = Xian("http://127.0.0.1:26657", chain_id="xian-test-1", wallet=wallet)

    assert client.chain_id == "xian-test-1"
    assert client.wallet is wallet
