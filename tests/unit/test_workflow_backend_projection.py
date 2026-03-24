import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from xian_py.models import IndexedEvent

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "examples" / "workflow_backend" / "projection.py"
SPEC = spec_from_file_location("workflow_backend_projection", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
PROJECTION_MODULE = module_from_spec(SPEC)
sys.modules[SPEC.name] = PROJECTION_MODULE
SPEC.loader.exec_module(PROJECTION_MODULE)
WorkflowProjection = PROJECTION_MODULE.WorkflowProjection


def _event(
    event_id: int,
    event_name: str,
    *,
    data: dict,
    data_indexed: dict | None = None,
) -> IndexedEvent:
    return IndexedEvent(
        id=event_id,
        tx_hash=f"tx-{event_id}",
        block_height=1,
        tx_index=0,
        event_index=0,
        contract="con_job_workflow",
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


def test_workflow_projection_tracks_items_and_activity(tmp_path: Path) -> None:
    projection = WorkflowProjection(
        tmp_path / "workflow.sqlite3", "con_job_workflow"
    )
    try:
        assert projection.apply_event(
            _event(
                1,
                "ItemSubmitted",
                data={
                    "item_id": "job-1",
                    "kind": "job",
                    "requester": "alice",
                },
            ),
            item_snapshot={
                "item_id": "job-1",
                "requester": "alice",
                "kind": "job",
                "payload_uri": "https://example.invalid/jobs/job-1",
                "metadata_ref": "",
                "status": "submitted",
                "worker": "",
                "result_uri": "",
                "failure_reason": "",
                "created_at": "2026-03-24T00:00:00Z",
                "updated_at": "2026-03-24T00:00:00Z",
            },
        )
        assert projection.apply_event(
            _event(
                2,
                "ItemClaimed",
                data={
                    "item_id": "job-1",
                    "worker": "worker-1",
                    "requester": "alice",
                },
            ),
            item_snapshot={
                "item_id": "job-1",
                "requester": "alice",
                "kind": "job",
                "payload_uri": "https://example.invalid/jobs/job-1",
                "metadata_ref": "",
                "status": "processing",
                "worker": "worker-1",
                "result_uri": "",
                "failure_reason": "",
                "created_at": "2026-03-24T00:00:00Z",
                "updated_at": "2026-03-24T00:01:00Z",
            },
        )
        assert projection.apply_event(
            _event(
                3,
                "ItemCompleted",
                data={
                    "item_id": "job-1",
                    "worker": "worker-1",
                    "result_uri": "https://example.invalid/results/job-1",
                },
            ),
            item_snapshot={
                "item_id": "job-1",
                "requester": "alice",
                "kind": "job",
                "payload_uri": "https://example.invalid/jobs/job-1",
                "metadata_ref": "",
                "status": "completed",
                "worker": "worker-1",
                "result_uri": "https://example.invalid/results/job-1",
                "failure_reason": "",
                "created_at": "2026-03-24T00:00:00Z",
                "updated_at": "2026-03-24T00:02:00Z",
            },
        )
        assert projection.apply_event(
            _event(
                4,
                "ItemSubmitted",
                data={
                    "item_id": "job-2",
                    "kind": "job",
                    "requester": "bob",
                },
            ),
            item_snapshot={
                "item_id": "job-2",
                "requester": "bob",
                "kind": "job",
                "payload_uri": "https://example.invalid/jobs/job-2",
                "metadata_ref": "meta-2",
                "status": "submitted",
                "worker": "",
                "result_uri": "",
                "failure_reason": "",
                "created_at": "2026-03-24T00:03:00Z",
                "updated_at": "2026-03-24T00:03:00Z",
            },
        )
        assert projection.apply_event(
            _event(
                5,
                "ItemCancelled",
                data={
                    "item_id": "job-2",
                    "actor": "bob",
                    "reason": "user cancelled",
                },
            ),
            item_snapshot={
                "item_id": "job-2",
                "requester": "bob",
                "kind": "job",
                "payload_uri": "https://example.invalid/jobs/job-2",
                "metadata_ref": "meta-2",
                "status": "cancelled",
                "worker": "",
                "result_uri": "",
                "failure_reason": "user cancelled",
                "created_at": "2026-03-24T00:03:00Z",
                "updated_at": "2026-03-24T00:04:00Z",
            },
        )

        summary = projection.get_summary()
        assert summary.item_count == 2
        assert summary.submitted_count == 0
        assert summary.processing_count == 0
        assert summary.completed_count == 1
        assert summary.cancelled_count == 1
        assert summary.failed_count == 0
        assert summary.activity_count == 5
        assert summary.last_event_id == 5

        job1 = projection.get_item("job-1")
        assert job1 is not None
        assert job1.status == "completed"
        assert job1.worker == "worker-1"

        cancelled = projection.list_items(status="cancelled", limit=10)
        assert [item.item_id for item in cancelled] == ["job-2"]

        recent = projection.list_activity(limit=10)
        assert [entry.event_id for entry in recent] == [5, 4, 3, 2, 1]

        item_activity = projection.list_activity(item_id="job-1", limit=10)
        assert [entry.event_id for entry in item_activity] == [3, 2, 1]

        health = projection.get_health()
        assert health["last_event_id"] == 5
        assert health["cursors"] == {
            "ItemCancelled": 5,
            "ItemClaimed": 2,
            "ItemCompleted": 3,
            "ItemSubmitted": 4,
        }

        assert (
            projection.apply_event(
                _event(
                    5,
                    "ItemCancelled",
                    data={
                        "item_id": "job-2",
                        "actor": "bob",
                        "reason": "user cancelled",
                    },
                ),
                item_snapshot={
                    "item_id": "job-2",
                    "requester": "bob",
                    "kind": "job",
                    "payload_uri": "https://example.invalid/jobs/job-2",
                    "metadata_ref": "meta-2",
                    "status": "cancelled",
                    "worker": "",
                    "result_uri": "",
                    "failure_reason": "user cancelled",
                    "created_at": "2026-03-24T00:03:00Z",
                    "updated_at": "2026-03-24T00:04:00Z",
                },
            )
            is False
        )
    finally:
        projection.close()


def test_workflow_projection_accepts_split_bds_event_payloads(
    tmp_path: Path,
) -> None:
    projection = WorkflowProjection(
        tmp_path / "workflow-split.sqlite3", "con_job_workflow"
    )
    try:
        assert projection.apply_event(
            _event(
                1,
                "ItemSubmitted",
                data={"requester": "alice"},
                data_indexed={"item_id": "job-1", "kind": "job"},
            ),
            item_snapshot={
                "item_id": "job-1",
                "requester": "alice",
                "kind": "job",
                "payload_uri": "https://example.invalid/jobs/job-1",
                "metadata_ref": "",
                "status": "submitted",
                "worker": "",
                "result_uri": "",
                "failure_reason": "",
                "created_at": "2026-03-24T00:00:00Z",
                "updated_at": "2026-03-24T00:00:00Z",
            },
        )

        item = projection.get_item("job-1")
        assert item is not None
        assert item.status == "submitted"
        assert item.requester == "alice"

        activity = projection.list_activity(limit=10)
        assert len(activity) == 1
        assert activity[0].item_id == "job-1"
        assert activity[0].actor == "alice"
    finally:
        projection.close()
