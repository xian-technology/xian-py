import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from xian_py.models import IndexedEvent

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "examples" / "credits_ledger" / "projection.py"
SPEC = spec_from_file_location("credits_ledger_projection", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
PROJECTION_MODULE = module_from_spec(SPEC)
sys.modules[SPEC.name] = PROJECTION_MODULE
SPEC.loader.exec_module(PROJECTION_MODULE)
CreditsLedgerProjection = PROJECTION_MODULE.CreditsLedgerProjection


def _event(
    event_id: int,
    event_name: str,
    *,
    data: dict,
    data_indexed: dict | None = None,
    tx_hash: str | None = None,
) -> IndexedEvent:
    return IndexedEvent(
        id=event_id,
        tx_hash=tx_hash or f"tx-{event_id}",
        block_height=1,
        tx_index=0,
        event_index=0,
        contract="con_credits_ledger",
        event=event_name,
        signer=None,
        caller=None,
        data_indexed=data_indexed,
        data=data,
        created="2026-03-24T00:00:00Z",
        raw={
            "id": event_id,
            "event": event_name,
            "data": data,
            "data_indexed": data_indexed,
        },
    )


def test_credits_ledger_projection_tracks_balances_and_summary(
    tmp_path: Path,
) -> None:
    projection = CreditsLedgerProjection(
        tmp_path / "credits.sqlite3",
        "con_credits_ledger",
    )
    try:
        assert projection.apply_event(
            _event(
                1,
                "Issue",
                data={"to": "alice", "amount": "10", "issuer": "operator"},
            )
        )
        assert projection.apply_event(
            _event(
                2,
                "Transfer",
                data={"from": "alice", "to": "bob", "amount": "3"},
            )
        )
        assert projection.apply_event(
            _event(
                3,
                "Burn",
                data={"from": "bob", "amount": "1", "actor": "bob"},
            )
        )

        summary = projection.get_summary()
        assert summary.total_issued == "10"
        assert summary.total_transferred == "3"
        assert summary.total_burned == "1"
        assert summary.projected_supply == "9"
        assert summary.last_event_id == 3
        assert summary.activity_count == 3
        assert summary.tracked_accounts == 2

        alice = projection.get_account("alice")
        assert alice.projected_balance == "7"
        assert alice.total_issued == "10"
        assert alice.total_sent == "3"
        assert alice.total_received == "0"
        assert alice.total_burned == "0"

        bob = projection.get_account("bob")
        assert bob.projected_balance == "2"
        assert bob.total_received == "3"
        assert bob.total_burned == "1"

        health = projection.get_health()
        assert health["last_event_id"] == 3
        assert health["cursors"] == {"Burn": 3, "Issue": 1, "Transfer": 2}

        all_activity = projection.list_activity(limit=10)
        assert [entry.event_id for entry in all_activity] == [3, 2, 1]

        alice_activity = projection.list_activity(address="alice", limit=10)
        assert [entry.event_id for entry in alice_activity] == [2, 1]

        # Re-applying the same event should be idempotent.
        assert (
            projection.apply_event(
                _event(
                    3,
                    "Burn",
                    data={"from": "bob", "amount": "1", "actor": "bob"},
                )
            )
            is False
        )
        assert projection.get_summary().activity_count == 3
    finally:
        projection.close()


def test_credits_ledger_projection_accepts_split_bds_event_payloads(
    tmp_path: Path,
) -> None:
    projection = CreditsLedgerProjection(
        tmp_path / "credits-split.sqlite3",
        "con_credits_ledger",
    )
    try:
        assert projection.apply_event(
            _event(
                1,
                "Issue",
                data={"amount": "10"},
                data_indexed={"to": "alice", "issuer": "operator"},
            )
        )
        assert projection.apply_event(
            _event(
                2,
                "Transfer",
                data={"amount": "4"},
                data_indexed={"from": "alice", "to": "bob"},
            )
        )
        assert projection.apply_event(
            _event(
                3,
                "Burn",
                data={"amount": "1"},
                data_indexed={"from": "bob", "actor": "operator"},
            )
        )

        assert projection.get_account("alice").projected_balance == "6"
        assert projection.get_account("bob").projected_balance == "3"
        assert projection.get_summary().projected_supply == "9"
    finally:
        projection.close()


def test_credits_ledger_projection_accepts_runtime_fixed_amounts(
    tmp_path: Path,
) -> None:
    projection = CreditsLedgerProjection(
        tmp_path / "credits-fixed.sqlite3",
        "con_credits_ledger",
    )
    try:
        assert projection.apply_event(
            _event(
                1,
                "Burn",
                data={"amount": {"__fixed__": "50.5"}},
                data_indexed={"from": "alice", "actor": "operator"},
            )
        )

        account = projection.get_account("alice")
        assert account.projected_balance == "-50.5"
        assert account.total_burned == "50.5"
        assert projection.get_summary().total_burned == "50.5"
        assert projection.get_summary().projected_supply == "-50.5"
    finally:
        projection.close()
