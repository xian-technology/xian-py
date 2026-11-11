import importlib
import sys
from pathlib import Path

from xian_py.models import TransactionReceipt, TransactionSubmission

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ensure_credits_submission_succeeded = importlib.import_module(
    "examples.credits_ledger.common"
).ensure_submission_succeeded
ensure_registry_submission_succeeded = importlib.import_module(
    "examples.registry_approval.common"
).ensure_submission_succeeded
ensure_workflow_submission_succeeded = importlib.import_module(
    "examples.workflow_backend.common"
).ensure_submission_succeeded


HELPERS = (
    ensure_credits_submission_succeeded,
    ensure_registry_submission_succeeded,
    ensure_workflow_submission_succeeded,
)


def successful_submission() -> TransactionSubmission:
    return TransactionSubmission(
        submitted=True,
        accepted=True,
        finalized=True,
        tx_hash="ABC",
        mode="checktx",
        nonce=1,
        chi_supplied=10,
        chi_estimated=8,
        message=None,
        response={},
        receipt=TransactionReceipt(
            success=True,
            tx_hash="ABC",
            message=None,
            transaction=None,
            execution=None,
            raw={},
        ),
    )


def failed_submission() -> TransactionSubmission:
    return TransactionSubmission(
        submitted=True,
        accepted=True,
        finalized=True,
        tx_hash="ABC",
        mode="checktx",
        nonce=1,
        chi_supplied=10,
        chi_estimated=8,
        message=None,
        response={},
        receipt=TransactionReceipt(
            success=False,
            tx_hash="ABC",
            message="boom",
            transaction=None,
            execution=None,
            raw={},
        ),
    )


def test_example_submission_helpers_accept_successful_receipts() -> None:
    submission = successful_submission()
    for helper in HELPERS:
        assert helper(submission, "demo") is submission


def test_example_submission_helpers_raise_for_failed_receipts() -> None:
    for helper in HELPERS:
        try:
            helper(failed_submission(), "demo")
        except RuntimeError as exc:
            assert "demo failed: boom" == str(exc)
        else:  # pragma: no cover - defensive
            raise AssertionError("helper did not raise for failed receipt")


def test_credits_projection_keeps_all_thirty_places(tmp_path):
    from examples.credits_ledger.projection import CreditsLedgerProjection
    from xian_py.models import IndexedEvent

    projection = CreditsLedgerProjection(tmp_path / "credits.sqlite3", "con_ledger")
    try:
        amount = "9007199254740993.000000000000000000000000000001"
        unit = "0.000000000000000000000000000001"
        for event_id, event, value, key in [(1, "Issue", amount, "to"), (2, "Burn", unit, "from")]:
            projection.apply_event(
                IndexedEvent.from_dict(
                    {
                        "id": event_id,
                        "event": event,
                        "contract": "con_ledger",
                        "data": {key: "alice", "amount": {"__fixed__": value}},
                    }
                )
            )
        assert projection.get_account("alice").total_issued == amount
        assert projection.get_summary().projected_supply == "9007199254740993"
    finally:
        projection.close()


def test_fastapi_sample_preserves_original_http_amount():
    import asyncio
    from decimal import Decimal

    import pytest

    pytest.importorskip("fastapi")
    from examples.contract_json import ContractJsonRequest
    from examples.fastapi_service import TransferRequest

    amount = "9007199254740993.123456789012345678901234567891"

    async def receive():
        return {
            "type": "http.request",
            "body": ('{"to_address":"alice","amount":' + amount + "}").encode(),
        }

    raw = asyncio.run(ContractJsonRequest({"type": "http"}, receive).json())
    assert TransferRequest.model_validate(raw).amount == Decimal(amount)
    with pytest.raises(ValueError):
        TransferRequest.model_validate({"to_address": "alice", "amount": Decimal("1e-31")})
