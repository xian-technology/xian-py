import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from xian_py.models import IndexedEvent

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "examples" / "registry_approval" / "projection.py"
SPEC = spec_from_file_location("registry_approval_projection", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
PROJECTION_MODULE = module_from_spec(SPEC)
sys.modules[SPEC.name] = PROJECTION_MODULE
SPEC.loader.exec_module(PROJECTION_MODULE)
RegistryApprovalProjection = PROJECTION_MODULE.RegistryApprovalProjection


def _event(
    event_id: int,
    event_name: str,
    *,
    contract: str,
    data: dict,
    data_indexed: dict | None = None,
) -> IndexedEvent:
    return IndexedEvent(
        id=event_id,
        tx_hash=f"tx-{event_id}",
        block_height=1,
        tx_index=0,
        event_index=0,
        contract=contract,
        event=event_name,
        signer=None,
        caller=None,
        data_indexed=data_indexed,
        data=data,
        created="2026-03-24T00:00:00Z",
        raw={
            "id": event_id,
            "contract": contract,
            "event": event_name,
            "data": data,
            "data_indexed": data_indexed,
        },
    )


def test_registry_approval_projection_tracks_proposals_records_and_activity(
    tmp_path: Path,
) -> None:
    projection = RegistryApprovalProjection(
        tmp_path / "registry.sqlite3",
        registry_contract="con_registry_records",
        approval_contract="con_registry_approval",
    )
    try:
        assert projection.apply_event(
            _event(
                1,
                "ProposalSubmitted",
                contract="con_registry_approval",
                data={
                    "proposal_id": 1,
                    "action": "upsert",
                    "record_id": "record-1",
                    "proposer": "alice",
                },
            ),
            proposal_snapshot={
                "proposal_id": 1,
                "action": "upsert",
                "record_id": "record-1",
                "owner": "alice",
                "uri": "https://example.invalid/record-1",
                "checksum": "abc123",
                "description": "First record",
                "reason": "",
                "proposer": "alice",
                "approved_count": 1,
                "threshold": 2,
                "executed": False,
                "created_at": "2026-03-24T00:00:00Z",
                "executed_at": None,
            },
        )
        assert projection.apply_event(
            _event(
                2,
                "ProposalApproved",
                contract="con_registry_approval",
                data={
                    "proposal_id": 1,
                    "approver": "bob",
                    "approved_count": 2,
                },
            ),
            proposal_snapshot={
                "proposal_id": 1,
                "action": "upsert",
                "record_id": "record-1",
                "owner": "alice",
                "uri": "https://example.invalid/record-1",
                "checksum": "abc123",
                "description": "First record",
                "reason": "",
                "proposer": "alice",
                "approved_count": 2,
                "threshold": 2,
                "executed": False,
                "created_at": "2026-03-24T00:00:00Z",
                "executed_at": None,
            },
        )
        assert projection.apply_event(
            _event(
                3,
                "ProposalExecuted",
                contract="con_registry_approval",
                data={
                    "proposal_id": 1,
                    "action": "upsert",
                    "record_id": "record-1",
                    "executor": "bob",
                },
            ),
            proposal_snapshot={
                "proposal_id": 1,
                "action": "upsert",
                "record_id": "record-1",
                "owner": "alice",
                "uri": "https://example.invalid/record-1",
                "checksum": "abc123",
                "description": "First record",
                "reason": "",
                "proposer": "alice",
                "approved_count": 2,
                "threshold": 2,
                "executed": True,
                "created_at": "2026-03-24T00:00:00Z",
                "executed_at": "2026-03-24T00:01:00Z",
            },
        )
        assert projection.apply_event(
            _event(
                4,
                "RecordUpserted",
                contract="con_registry_records",
                data={
                    "record_id": "record-1",
                    "owner": "alice",
                    "version": 1,
                    "actor": "con_registry_approval",
                },
            ),
            record_snapshot={
                "record_id": "record-1",
                "owner": "alice",
                "uri": "https://example.invalid/record-1",
                "checksum": "abc123",
                "description": "First record",
                "status": "active",
                "revoked_reason": "",
                "version": 1,
                "updated_at": "2026-03-24T00:01:00Z",
            },
        )
        assert projection.apply_event(
            _event(
                5,
                "RecordRevoked",
                contract="con_registry_records",
                data={
                    "record_id": "record-1",
                    "reason": "expired",
                    "actor": "con_registry_approval",
                },
            ),
            record_snapshot={
                "record_id": "record-1",
                "owner": "alice",
                "uri": "https://example.invalid/record-1",
                "checksum": "abc123",
                "description": "First record",
                "status": "revoked",
                "revoked_reason": "expired",
                "version": 1,
                "updated_at": "2026-03-24T00:02:00Z",
            },
        )

        summary = projection.get_summary()
        assert summary.proposal_count == 1
        assert summary.pending_proposals == 0
        assert summary.executed_proposals == 1
        assert summary.record_count == 1
        assert summary.active_records == 0
        assert summary.revoked_records == 1
        assert summary.approval_count == 1
        assert summary.last_event_id == 5

        proposal = projection.get_proposal(1)
        assert proposal is not None
        assert proposal.status == "executed"
        assert proposal.approved_count == 2
        assert proposal.executed is True

        approvals = projection.list_approvals(1)
        assert len(approvals) == 1
        assert approvals[0].approver == "bob"
        assert approvals[0].approved_count == 2

        record = projection.get_record("record-1")
        assert record is not None
        assert record.status == "revoked"
        assert record.revoked_reason == "expired"

        recent_activity = projection.list_activity(limit=10)
        assert [entry.event_id for entry in recent_activity] == [5, 4, 3, 2, 1]

        proposal_activity = projection.list_activity(proposal_id=1, limit=10)
        assert [entry.event_id for entry in proposal_activity] == [3, 2, 1]

        record_activity = projection.list_activity(
            record_id="record-1", limit=10
        )
        assert [entry.event_id for entry in record_activity] == [5, 4, 3, 1]

        health = projection.get_health()
        assert health["last_event_id"] == 5
        assert health["cursors"] == {
            "con_registry_approval:ProposalApproved": 2,
            "con_registry_approval:ProposalExecuted": 3,
            "con_registry_approval:ProposalSubmitted": 1,
            "con_registry_records:RecordRevoked": 5,
            "con_registry_records:RecordUpserted": 4,
        }

        assert (
            projection.apply_event(
                _event(
                    5,
                    "RecordRevoked",
                    contract="con_registry_records",
                    data={
                        "record_id": "record-1",
                        "reason": "expired",
                        "actor": "con_registry_approval",
                    },
                ),
                record_snapshot={
                    "record_id": "record-1",
                    "owner": "alice",
                    "uri": "https://example.invalid/record-1",
                    "checksum": "abc123",
                    "description": "First record",
                    "status": "revoked",
                    "revoked_reason": "expired",
                    "version": 1,
                    "updated_at": "2026-03-24T00:02:00Z",
                },
            )
            is False
        )
    finally:
        projection.close()


def test_registry_approval_projection_accepts_split_bds_event_payloads(
    tmp_path: Path,
) -> None:
    projection = RegistryApprovalProjection(
        tmp_path / "registry-split.sqlite3",
        registry_contract="con_registry_records",
        approval_contract="con_registry_approval",
    )
    try:
        assert projection.apply_event(
            _event(
                1,
                "ProposalSubmitted",
                contract="con_registry_approval",
                data={"proposer": "alice"},
                data_indexed={
                    "proposal_id": 1,
                    "action": "upsert",
                    "record_id": "record-1",
                },
            ),
            proposal_snapshot={
                "proposal_id": 1,
                "action": "upsert",
                "record_id": "record-1",
                "owner": "alice",
                "uri": "https://example.invalid/record-1",
                "checksum": "abc123",
                "description": "First record",
                "reason": "",
                "proposer": "alice",
                "approved_count": 1,
                "threshold": 2,
                "executed": False,
                "created_at": "2026-03-24T00:00:00Z",
                "executed_at": None,
            },
        )

        proposal = projection.get_proposal(1)
        assert proposal is not None
        assert proposal.record_id == "record-1"
        assert proposal.status == "pending"

        activity = projection.list_activity(limit=10)
        assert len(activity) == 1
        assert activity[0].proposal_id == 1
        assert activity[0].record_id == "record-1"
        assert activity[0].actor == "alice"
    finally:
        projection.close()
