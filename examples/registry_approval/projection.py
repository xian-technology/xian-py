from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xian_py.models import IndexedEvent


def _bool_to_int(value: bool) -> int:
    return 1 if value else 0


def _int_to_bool(value: Any) -> bool:
    return bool(int(value or 0))


def _as_int(value: Any) -> int:
    return int(value) if value is not None else 0


@dataclass(frozen=True)
class RegistryProjectionSummary:
    registry_contract: str
    approval_contract: str
    proposal_count: int
    pending_proposals: int
    executed_proposals: int
    record_count: int
    active_records: int
    revoked_records: int
    approval_count: int
    last_event_id: int | None


@dataclass(frozen=True)
class ProjectedProposal:
    proposal_id: int
    action: str | None
    record_id: str | None
    owner: str | None
    uri: str | None
    checksum: str | None
    description: str | None
    reason: str | None
    proposer: str | None
    approved_count: int
    threshold: int
    executed: bool
    status: str
    created_at: str | None
    executed_at: str | None
    last_event_id: int | None


@dataclass(frozen=True)
class ProjectedRecord:
    record_id: str
    owner: str | None
    uri: str | None
    checksum: str | None
    description: str | None
    status: str | None
    revoked_reason: str | None
    version: int
    updated_at: str | None
    last_event_id: int | None


@dataclass(frozen=True)
class ProjectedApproval:
    event_id: int
    proposal_id: int
    approver: str | None
    approved_count: int
    created: str | None
    tx_hash: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class RegistryActivityEntry:
    event_id: int
    contract: str | None
    event_name: str
    tx_hash: str | None
    block_height: int | None
    proposal_id: int | None
    record_id: str | None
    actor: str | None
    approved_count: int | None
    created: str | None
    raw: dict[str, Any]


class RegistryApprovalProjection:
    def __init__(self, path: Path, *, registry_contract: str, approval_contract: str):
        self.path = path
        self.registry_contract = registry_contract
        self.approval_contract = approval_contract
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
                CREATE TABLE IF NOT EXISTS proposal_projection (
                    proposal_id INTEGER PRIMARY KEY,
                    action TEXT,
                    record_id TEXT,
                    owner TEXT,
                    uri TEXT,
                    checksum TEXT,
                    description TEXT,
                    reason TEXT,
                    proposer TEXT,
                    approved_count INTEGER NOT NULL,
                    threshold INTEGER NOT NULL,
                    executed INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT,
                    executed_at TEXT,
                    last_event_id INTEGER
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS record_projection (
                    record_id TEXT PRIMARY KEY,
                    owner TEXT,
                    uri TEXT,
                    checksum TEXT,
                    description TEXT,
                    status TEXT,
                    revoked_reason TEXT,
                    version INTEGER NOT NULL,
                    updated_at TEXT,
                    last_event_id INTEGER
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS proposal_approvals (
                    event_id INTEGER PRIMARY KEY,
                    proposal_id INTEGER NOT NULL,
                    approver TEXT,
                    approved_count INTEGER NOT NULL,
                    created TEXT,
                    tx_hash TEXT,
                    raw_json TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS registry_activity (
                    event_id INTEGER PRIMARY KEY,
                    contract TEXT,
                    event_name TEXT NOT NULL,
                    tx_hash TEXT,
                    block_height INTEGER,
                    proposal_id INTEGER,
                    record_id TEXT,
                    actor TEXT,
                    approved_count INTEGER,
                    created TEXT,
                    raw_json TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_registry_activity_record
                ON registry_activity(record_id, event_id DESC)
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_registry_activity_proposal
                ON registry_activity(proposal_id, event_id DESC)
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_proposal_projection_status
                ON proposal_projection(status, last_event_id DESC)
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_record_projection_status
                ON record_projection(status, last_event_id DESC)
                """
            )

    def get_cursor(self, contract: str, event_name: str) -> int:
        row = self.connection.execute(
            "SELECT value FROM projection_state WHERE name = ?",
            (f"cursor:{contract}:{event_name}",),
        ).fetchone()
        return int(row["value"]) if row is not None else 0

    def get_cursors(self) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT name, value FROM projection_state WHERE name LIKE 'cursor:%'"
        ).fetchall()
        return {
            str(row["name"]).split("cursor:", 1)[1]: int(row["value"])
            for row in rows
        }

    def apply_event(
        self,
        event: IndexedEvent,
        *,
        proposal_snapshot: dict[str, Any] | None = None,
        record_snapshot: dict[str, Any] | None = None,
    ) -> bool:
        if event.id is None:
            raise ValueError("Projection requires event IDs")
        if event.event is None:
            raise ValueError("Projection requires event names")

        existing = self.connection.execute(
            "SELECT 1 FROM registry_activity WHERE event_id = ?",
            (event.id,),
        ).fetchone()
        if existing is not None:
            self._set_cursor(event.contract or "", event.event, event.id)
            return False

        data = event.data or {}
        proposal_id = data.get("proposal_id")
        record_id = data.get("record_id")
        actor = (
            data.get("proposer")
            or data.get("approver")
            or data.get("executor")
            or data.get("actor")
        )
        approved_count = (
            _as_int(data.get("approved_count"))
            if data.get("approved_count") is not None
            else None
        )

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO registry_activity (
                    event_id,
                    contract,
                    event_name,
                    tx_hash,
                    block_height,
                    proposal_id,
                    record_id,
                    actor,
                    approved_count,
                    created,
                    raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.contract,
                    event.event,
                    event.tx_hash,
                    event.block_height,
                    proposal_id,
                    record_id,
                    actor,
                    approved_count,
                    event.created,
                    json.dumps(event.raw, sort_keys=True, default=str),
                ),
            )

            if proposal_snapshot is not None and proposal_id is not None:
                self._upsert_proposal(
                    proposal_id=int(proposal_id),
                    snapshot=proposal_snapshot,
                    event_id=event.id,
                )

            if event.event == "ProposalApproved" and proposal_id is not None:
                self.connection.execute(
                    """
                    INSERT INTO proposal_approvals (
                        event_id,
                        proposal_id,
                        approver,
                        approved_count,
                        created,
                        tx_hash,
                        raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.id,
                        int(proposal_id),
                        data.get("approver"),
                        _as_int(data.get("approved_count")),
                        event.created,
                        event.tx_hash,
                        json.dumps(event.raw, sort_keys=True, default=str),
                    ),
                )

            if record_snapshot is not None and record_id is not None:
                self._upsert_record(
                    record_id=str(record_id),
                    snapshot=record_snapshot,
                    event_id=event.id,
                )

            self._set_cursor(event.contract or "", event.event, event.id)
        return True

    def get_summary(self) -> RegistryProjectionSummary:
        proposal_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM proposal_projection"
            ).fetchone()[0]
        )
        pending_proposals = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM proposal_projection WHERE status = 'pending'"
            ).fetchone()[0]
        )
        executed_proposals = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM proposal_projection WHERE status = 'executed'"
            ).fetchone()[0]
        )
        record_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM record_projection"
            ).fetchone()[0]
        )
        active_records = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM record_projection WHERE status = 'active'"
            ).fetchone()[0]
        )
        revoked_records = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM record_projection WHERE status = 'revoked'"
            ).fetchone()[0]
        )
        approval_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM proposal_approvals"
            ).fetchone()[0]
        )
        last_event_id = self.connection.execute(
            "SELECT MAX(event_id) FROM registry_activity"
        ).fetchone()[0]
        return RegistryProjectionSummary(
            registry_contract=self.registry_contract,
            approval_contract=self.approval_contract,
            proposal_count=proposal_count,
            pending_proposals=pending_proposals,
            executed_proposals=executed_proposals,
            record_count=record_count,
            active_records=active_records,
            revoked_records=revoked_records,
            approval_count=approval_count,
            last_event_id=last_event_id,
        )

    def get_proposal(self, proposal_id: int) -> ProjectedProposal | None:
        row = self.connection.execute(
            "SELECT * FROM proposal_projection WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        return self._proposal_from_row(row)

    def list_proposals(
        self,
        *,
        limit: int = 50,
        status: str | None = None,
        before_event_id: int | None = None,
        record_id: str | None = None,
    ) -> list[ProjectedProposal]:
        query = "SELECT * FROM proposal_projection"
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if before_event_id is not None:
            clauses.append("last_event_id < ?")
            params.append(before_event_id)
        if record_id is not None:
            clauses.append("record_id = ?")
            params.append(record_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY last_event_id DESC, proposal_id DESC LIMIT ?"
        params.append(limit)
        rows = self.connection.execute(query, params).fetchall()
        return [self._proposal_from_row(row) for row in rows]

    def get_record(self, record_id: str) -> ProjectedRecord | None:
        row = self.connection.execute(
            "SELECT * FROM record_projection WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            return None
        return self._record_from_row(row)

    def list_records(
        self,
        *,
        limit: int = 50,
        status: str | None = None,
        before_event_id: int | None = None,
    ) -> list[ProjectedRecord]:
        query = "SELECT * FROM record_projection"
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
        query += " ORDER BY last_event_id DESC, record_id ASC LIMIT ?"
        params.append(limit)
        rows = self.connection.execute(query, params).fetchall()
        return [self._record_from_row(row) for row in rows]

    def list_activity(
        self,
        *,
        limit: int = 50,
        before_id: int | None = None,
        record_id: str | None = None,
        proposal_id: int | None = None,
    ) -> list[RegistryActivityEntry]:
        query = "SELECT * FROM registry_activity"
        clauses: list[str] = []
        params: list[Any] = []
        if before_id is not None:
            clauses.append("event_id < ?")
            params.append(before_id)
        if record_id is not None:
            clauses.append("record_id = ?")
            params.append(record_id)
        if proposal_id is not None:
            clauses.append("proposal_id = ?")
            params.append(proposal_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY event_id DESC LIMIT ?"
        params.append(limit)
        rows = self.connection.execute(query, params).fetchall()
        return [
            RegistryActivityEntry(
                event_id=int(row["event_id"]),
                contract=row["contract"],
                event_name=str(row["event_name"]),
                tx_hash=row["tx_hash"],
                block_height=row["block_height"],
                proposal_id=row["proposal_id"],
                record_id=row["record_id"],
                actor=row["actor"],
                approved_count=row["approved_count"],
                created=row["created"],
                raw=json.loads(str(row["raw_json"])),
            )
            for row in rows
        ]

    def list_approvals(
        self,
        proposal_id: int,
    ) -> list[ProjectedApproval]:
        rows = self.connection.execute(
            """
            SELECT * FROM proposal_approvals
            WHERE proposal_id = ?
            ORDER BY event_id ASC
            """,
            (proposal_id,),
        ).fetchall()
        return [
            ProjectedApproval(
                event_id=int(row["event_id"]),
                proposal_id=int(row["proposal_id"]),
                approver=row["approver"],
                approved_count=int(row["approved_count"]),
                created=row["created"],
                tx_hash=row["tx_hash"],
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
            "registry_contract": summary.registry_contract,
            "approval_contract": summary.approval_contract,
            "last_event_id": summary.last_event_id,
            "proposal_count": summary.proposal_count,
            "record_count": summary.record_count,
            "cursors": self.get_cursors(),
        }

    def _upsert_proposal(
        self,
        *,
        proposal_id: int,
        snapshot: dict[str, Any],
        event_id: int,
    ) -> None:
        executed = bool(snapshot.get("executed"))
        status = "executed" if executed else "pending"
        self.connection.execute(
            """
            INSERT INTO proposal_projection (
                proposal_id,
                action,
                record_id,
                owner,
                uri,
                checksum,
                description,
                reason,
                proposer,
                approved_count,
                threshold,
                executed,
                status,
                created_at,
                executed_at,
                last_event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(proposal_id) DO UPDATE SET
                action = excluded.action,
                record_id = excluded.record_id,
                owner = excluded.owner,
                uri = excluded.uri,
                checksum = excluded.checksum,
                description = excluded.description,
                reason = excluded.reason,
                proposer = excluded.proposer,
                approved_count = excluded.approved_count,
                threshold = excluded.threshold,
                executed = excluded.executed,
                status = excluded.status,
                created_at = excluded.created_at,
                executed_at = excluded.executed_at,
                last_event_id = excluded.last_event_id
            """,
            (
                proposal_id,
                snapshot.get("action"),
                snapshot.get("record_id"),
                snapshot.get("owner"),
                snapshot.get("uri"),
                snapshot.get("checksum"),
                snapshot.get("description"),
                snapshot.get("reason"),
                snapshot.get("proposer"),
                _as_int(snapshot.get("approved_count")),
                _as_int(snapshot.get("threshold")),
                _bool_to_int(executed),
                status,
                snapshot.get("created_at"),
                snapshot.get("executed_at"),
                event_id,
            ),
        )

    def _upsert_record(
        self,
        *,
        record_id: str,
        snapshot: dict[str, Any],
        event_id: int,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO record_projection (
                record_id,
                owner,
                uri,
                checksum,
                description,
                status,
                revoked_reason,
                version,
                updated_at,
                last_event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_id) DO UPDATE SET
                owner = excluded.owner,
                uri = excluded.uri,
                checksum = excluded.checksum,
                description = excluded.description,
                status = excluded.status,
                revoked_reason = excluded.revoked_reason,
                version = excluded.version,
                updated_at = excluded.updated_at,
                last_event_id = excluded.last_event_id
            """,
            (
                record_id,
                snapshot.get("owner"),
                snapshot.get("uri"),
                snapshot.get("checksum"),
                snapshot.get("description"),
                snapshot.get("status"),
                snapshot.get("revoked_reason"),
                _as_int(snapshot.get("version")),
                snapshot.get("updated_at"),
                event_id,
            ),
        )

    def _set_cursor(self, contract: str, event_name: str, event_id: int) -> None:
        self.connection.execute(
            """
            INSERT INTO projection_state (name, value)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET value = excluded.value
            """,
            (f"cursor:{contract}:{event_name}", str(event_id)),
        )

    @staticmethod
    def _proposal_from_row(row: sqlite3.Row) -> ProjectedProposal:
        return ProjectedProposal(
            proposal_id=int(row["proposal_id"]),
            action=row["action"],
            record_id=row["record_id"],
            owner=row["owner"],
            uri=row["uri"],
            checksum=row["checksum"],
            description=row["description"],
            reason=row["reason"],
            proposer=row["proposer"],
            approved_count=int(row["approved_count"]),
            threshold=int(row["threshold"]),
            executed=_int_to_bool(row["executed"]),
            status=str(row["status"]),
            created_at=row["created_at"],
            executed_at=row["executed_at"],
            last_event_id=row["last_event_id"],
        )

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> ProjectedRecord:
        return ProjectedRecord(
            record_id=str(row["record_id"]),
            owner=row["owner"],
            uri=row["uri"],
            checksum=row["checksum"],
            description=row["description"],
            status=row["status"],
            revoked_reason=row["revoked_reason"],
            version=int(row["version"]),
            updated_at=row["updated_at"],
            last_event_id=row["last_event_id"],
        )
