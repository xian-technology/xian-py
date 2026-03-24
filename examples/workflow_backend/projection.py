from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xian_py.models import IndexedEvent


@dataclass(frozen=True)
class WorkflowProjectionSummary:
    workflow_contract: str
    item_count: int
    submitted_count: int
    processing_count: int
    completed_count: int
    failed_count: int
    cancelled_count: int
    activity_count: int
    last_event_id: int | None


@dataclass(frozen=True)
class ProjectedWorkflowItem:
    item_id: str
    requester: str | None
    kind: str | None
    payload_uri: str | None
    metadata_ref: str | None
    status: str | None
    worker: str | None
    result_uri: str | None
    failure_reason: str | None
    created_at: str | None
    updated_at: str | None
    last_event_id: int | None


@dataclass(frozen=True)
class WorkflowActivityEntry:
    event_id: int
    event_name: str
    tx_hash: str | None
    block_height: int | None
    item_id: str | None
    actor: str | None
    created: str | None
    raw: dict[str, Any]


class WorkflowProjection:
    def __init__(self, path: Path, workflow_contract: str) -> None:
        self.path = path
        self.workflow_contract = workflow_contract
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.connection.close()

    def _init_schema(self) -> None:
        with self.connection:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS projection_state (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_items (
                    item_id TEXT PRIMARY KEY,
                    requester TEXT,
                    kind TEXT,
                    payload_uri TEXT,
                    metadata_ref TEXT,
                    status TEXT,
                    worker TEXT,
                    result_uri TEXT,
                    failure_reason TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    last_event_id INTEGER
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_activity (
                    event_id INTEGER PRIMARY KEY,
                    event_name TEXT NOT NULL,
                    tx_hash TEXT,
                    block_height INTEGER,
                    item_id TEXT,
                    actor TEXT,
                    created TEXT,
                    raw_json TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_workflow_items_status
                ON workflow_items(status, last_event_id DESC)
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_workflow_activity_item
                ON workflow_activity(item_id, event_id DESC)
                """
            )

    def get_cursor(self, event_name: str) -> int:
        row = self.connection.execute(
            "SELECT value FROM projection_state WHERE name = ?",
            (f"cursor:{event_name}",),
        ).fetchone()
        return int(row["value"]) if row is not None else 0

    def get_cursors(self) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT name, value FROM projection_state WHERE name LIKE 'cursor:%'"
        ).fetchall()
        return {
            str(row["name"]).split(":", 1)[1]: int(row["value"]) for row in rows
        }

    def apply_event(
        self,
        event: IndexedEvent,
        *,
        item_snapshot: dict[str, Any] | None = None,
    ) -> bool:
        if event.id is None:
            raise ValueError("Projection requires event IDs")
        if event.event is None:
            raise ValueError("Projection requires event names")

        existing = self.connection.execute(
            "SELECT 1 FROM workflow_activity WHERE event_id = ?",
            (event.id,),
        ).fetchone()
        if existing is not None:
            self._set_cursor(event.event, event.id)
            return False

        data = event.data or {}
        actor = data.get("worker") or data.get("requester") or data.get("actor")
        item_id = data.get("item_id")

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO workflow_activity (
                    event_id,
                    event_name,
                    tx_hash,
                    block_height,
                    item_id,
                    actor,
                    created,
                    raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.event,
                    event.tx_hash,
                    event.block_height,
                    item_id,
                    actor,
                    event.created,
                    json.dumps(event.raw, sort_keys=True, default=str),
                ),
            )
            if item_snapshot is not None and item_id is not None:
                self._upsert_item(
                    item_id=str(item_id),
                    snapshot=item_snapshot,
                    event_id=event.id,
                )
            self._set_cursor(event.event, event.id)
        return True

    def get_summary(self) -> WorkflowProjectionSummary:
        item_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM workflow_items"
            ).fetchone()[0]
        )
        submitted_count = self._status_count("submitted")
        processing_count = self._status_count("processing")
        completed_count = self._status_count("completed")
        failed_count = self._status_count("failed")
        cancelled_count = self._status_count("cancelled")
        activity_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM workflow_activity"
            ).fetchone()[0]
        )
        last_event_id = self.connection.execute(
            "SELECT MAX(event_id) FROM workflow_activity"
        ).fetchone()[0]
        return WorkflowProjectionSummary(
            workflow_contract=self.workflow_contract,
            item_count=item_count,
            submitted_count=submitted_count,
            processing_count=processing_count,
            completed_count=completed_count,
            failed_count=failed_count,
            cancelled_count=cancelled_count,
            activity_count=activity_count,
            last_event_id=last_event_id,
        )

    def get_item(self, item_id: str) -> ProjectedWorkflowItem | None:
        row = self.connection.execute(
            "SELECT * FROM workflow_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return self._item_from_row(row)

    def list_items(
        self,
        *,
        limit: int = 50,
        status: str | None = None,
        before_event_id: int | None = None,
    ) -> list[ProjectedWorkflowItem]:
        query = "SELECT * FROM workflow_items"
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if before_event_id is not None:
            clauses.append("last_event_id < ?")
            params.append(before_event_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY last_event_id DESC, item_id ASC LIMIT ?"
        params.append(limit)
        rows = self.connection.execute(query, params).fetchall()
        return [self._item_from_row(row) for row in rows]

    def list_activity(
        self,
        *,
        limit: int = 50,
        before_id: int | None = None,
        item_id: str | None = None,
    ) -> list[WorkflowActivityEntry]:
        query = "SELECT * FROM workflow_activity"
        clauses: list[str] = []
        params: list[Any] = []
        if before_id is not None:
            clauses.append("event_id < ?")
            params.append(before_id)
        if item_id is not None:
            clauses.append("item_id = ?")
            params.append(item_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY event_id DESC LIMIT ?"
        params.append(limit)
        rows = self.connection.execute(query, params).fetchall()
        return [
            WorkflowActivityEntry(
                event_id=int(row["event_id"]),
                event_name=str(row["event_name"]),
                tx_hash=row["tx_hash"],
                block_height=row["block_height"],
                item_id=row["item_id"],
                actor=row["actor"],
                created=row["created"],
                raw=json.loads(str(row["raw_json"])),
            )
            for row in rows
        ]

    def get_health(self) -> dict[str, Any]:
        summary = self.get_summary()
        return {
            "path": str(self.path),
            "exists": self.path.exists(),
            "size_bytes": self.path.stat().st_size if self.path.exists() else 0,
            "workflow_contract": summary.workflow_contract,
            "last_event_id": summary.last_event_id,
            "item_count": summary.item_count,
            "activity_count": summary.activity_count,
            "cursors": self.get_cursors(),
        }

    def _upsert_item(
        self,
        *,
        item_id: str,
        snapshot: dict[str, Any],
        event_id: int,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO workflow_items (
                item_id,
                requester,
                kind,
                payload_uri,
                metadata_ref,
                status,
                worker,
                result_uri,
                failure_reason,
                created_at,
                updated_at,
                last_event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_id) DO UPDATE SET
                requester = excluded.requester,
                kind = excluded.kind,
                payload_uri = excluded.payload_uri,
                metadata_ref = excluded.metadata_ref,
                status = excluded.status,
                worker = excluded.worker,
                result_uri = excluded.result_uri,
                failure_reason = excluded.failure_reason,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                last_event_id = excluded.last_event_id
            """,
            (
                item_id,
                snapshot.get("requester"),
                snapshot.get("kind"),
                snapshot.get("payload_uri"),
                snapshot.get("metadata_ref"),
                snapshot.get("status"),
                snapshot.get("worker"),
                snapshot.get("result_uri"),
                snapshot.get("failure_reason"),
                snapshot.get("created_at"),
                snapshot.get("updated_at"),
                event_id,
            ),
        )

    def _set_cursor(self, event_name: str, event_id: int) -> None:
        self.connection.execute(
            """
            INSERT INTO projection_state (name, value)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET value = excluded.value
            """,
            (f"cursor:{event_name}", str(event_id)),
        )

    def _status_count(self, status: str) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM workflow_items WHERE status = ?",
                (status,),
            ).fetchone()[0]
        )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> ProjectedWorkflowItem:
        return ProjectedWorkflowItem(
            item_id=str(row["item_id"]),
            requester=row["requester"],
            kind=row["kind"],
            payload_uri=row["payload_uri"],
            metadata_ref=row["metadata_ref"],
            status=row["status"],
            worker=row["worker"],
            result_uri=row["result_uri"],
            failure_reason=row["failure_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_event_id=row["last_event_id"],
        )
