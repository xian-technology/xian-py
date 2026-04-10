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
