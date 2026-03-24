from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from xian_py.models import IndexedEvent

ZERO = Decimal("0")


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Cannot coerce {value!r} to Decimal") from exc


def _decimal_to_string(value: Decimal) -> str:
    normalized = format(value, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


@dataclass(frozen=True)
class ProjectionSummary:
    contract: str
    total_issued: str
    total_burned: str
    total_transferred: str
    projected_supply: str
    last_event_id: int | None
    activity_count: int
    tracked_accounts: int


@dataclass(frozen=True)
class AccountProjection:
    address: str
    projected_balance: str
    total_issued: str
    total_received: str
    total_sent: str
    total_burned: str
    last_event_id: int | None


@dataclass(frozen=True)
class ActivityEntry:
    event_id: int
    event_name: str
    tx_hash: str | None
    block_height: int | None
    account_from: str | None
    account_to: str | None
    actor: str | None
    amount: str | None
    created: str | None
    raw: dict[str, Any]


class CreditsLedgerProjection:
    def __init__(self, path: Path, contract: str) -> None:
        self.path = path
        self.contract = contract
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
                CREATE TABLE IF NOT EXISTS ledger_summary (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    contract TEXT NOT NULL,
                    total_issued TEXT NOT NULL,
                    total_burned TEXT NOT NULL,
                    total_transferred TEXT NOT NULL,
                    projected_supply TEXT NOT NULL,
                    last_event_id INTEGER
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS account_balances (
                    address TEXT PRIMARY KEY,
                    balance TEXT NOT NULL,
                    issued TEXT NOT NULL,
                    received TEXT NOT NULL,
                    sent TEXT NOT NULL,
                    burned TEXT NOT NULL,
                    last_event_id INTEGER
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ledger_events (
                    event_id INTEGER PRIMARY KEY,
                    event_name TEXT NOT NULL,
                    tx_hash TEXT,
                    block_height INTEGER,
                    tx_index INTEGER,
                    event_index INTEGER,
                    account_from TEXT,
                    account_to TEXT,
                    actor TEXT,
                    amount TEXT,
                    created TEXT,
                    raw_json TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ledger_events_from
                ON ledger_events(account_from, event_id DESC)
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ledger_events_to
                ON ledger_events(account_to, event_id DESC)
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ledger_events_actor
                ON ledger_events(actor, event_id DESC)
                """
            )
            self.connection.execute(
                """
                INSERT OR IGNORE INTO ledger_summary (
                    id,
                    contract,
                    total_issued,
                    total_burned,
                    total_transferred,
                    projected_supply,
                    last_event_id
                ) VALUES (1, ?, '0', '0', '0', '0', NULL)
                """,
                (self.contract,),
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

    def apply_event(self, event: IndexedEvent) -> bool:
        if event.id is None:
            raise ValueError("Projection requires event IDs")

        existing = self.connection.execute(
            "SELECT 1 FROM ledger_events WHERE event_id = ?",
            (event.id,),
        ).fetchone()
        if existing is not None:
            self._set_cursor(event.event or "", event.id)
            return False

        data = event.data or {}
        amount = _to_decimal(data.get("amount"))
        account_from = data.get("from")
        account_to = data.get("to")
        actor = data.get("actor") or data.get("issuer")
        event_name = event.event or ""

        with self.connection:
            self.connection.execute(
                """
                INSERT INTO ledger_events (
                    event_id,
                    event_name,
                    tx_hash,
                    block_height,
                    tx_index,
                    event_index,
                    account_from,
                    account_to,
                    actor,
                    amount,
                    created,
                    raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event_name,
                    event.tx_hash,
                    event.block_height,
                    event.tx_index,
                    event.event_index,
                    account_from,
                    account_to,
                    actor,
                    _decimal_to_string(amount) if data.get("amount") is not None else None,
                    event.created,
                    json.dumps(event.raw, sort_keys=True, default=str),
                ),
            )

            if event_name == "Issue":
                self._upsert_account(
                    str(account_to),
                    balance_delta=amount,
                    issued_delta=amount,
                    event_id=event.id,
                )
                self._update_summary(
                    issued_delta=amount,
                    supply_delta=amount,
                    event_id=event.id,
                )
            elif event_name == "Transfer":
                self._upsert_account(
                    str(account_from),
                    balance_delta=-amount,
                    sent_delta=amount,
                    event_id=event.id,
                )
                self._upsert_account(
                    str(account_to),
                    balance_delta=amount,
                    received_delta=amount,
                    event_id=event.id,
                )
                self._update_summary(
                    transferred_delta=amount,
                    event_id=event.id,
                )
            elif event_name == "Burn":
                self._upsert_account(
                    str(account_from),
                    balance_delta=-amount,
                    burned_delta=amount,
                    event_id=event.id,
                )
                self._update_summary(
                    burned_delta=amount,
                    supply_delta=-amount,
                    event_id=event.id,
                )
            else:
                self._update_summary(event_id=event.id)

            self._set_cursor(event_name, event.id)
        return True

    def get_summary(self) -> ProjectionSummary:
        row = self.connection.execute(
            """
            SELECT
                contract,
                total_issued,
                total_burned,
                total_transferred,
                projected_supply,
                last_event_id
            FROM ledger_summary
            WHERE id = 1
            """
        ).fetchone()
        activity_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM ledger_events"
            ).fetchone()[0]
        )
        tracked_accounts = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM account_balances"
            ).fetchone()[0]
        )
        return ProjectionSummary(
            contract=str(row["contract"]),
            total_issued=str(row["total_issued"]),
            total_burned=str(row["total_burned"]),
            total_transferred=str(row["total_transferred"]),
            projected_supply=str(row["projected_supply"]),
            last_event_id=row["last_event_id"],
            activity_count=activity_count,
            tracked_accounts=tracked_accounts,
        )

    def get_account(self, address: str) -> AccountProjection:
        row = self.connection.execute(
            """
            SELECT
                balance,
                issued,
                received,
                sent,
                burned,
                last_event_id
            FROM account_balances
            WHERE address = ?
            """,
            (address,),
        ).fetchone()
        if row is None:
            return AccountProjection(
                address=address,
                projected_balance="0",
                total_issued="0",
                total_received="0",
                total_sent="0",
                total_burned="0",
                last_event_id=None,
            )
        return AccountProjection(
            address=address,
            projected_balance=str(row["balance"]),
            total_issued=str(row["issued"]),
            total_received=str(row["received"]),
            total_sent=str(row["sent"]),
            total_burned=str(row["burned"]),
            last_event_id=row["last_event_id"],
        )

    def list_activity(
        self,
        *,
        limit: int = 50,
        before_id: int | None = None,
        address: str | None = None,
    ) -> list[ActivityEntry]:
        query = """
            SELECT
                event_id,
                event_name,
                tx_hash,
                block_height,
                account_from,
                account_to,
                actor,
                amount,
                created,
                raw_json
            FROM ledger_events
        """
        params: list[Any] = []
        clauses: list[str] = []
        if address is not None:
            clauses.append(
                "(account_from = ? OR account_to = ? OR actor = ?)"
            )
            params.extend([address, address, address])
        if before_id is not None:
            clauses.append("event_id < ?")
            params.append(before_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY event_id DESC LIMIT ?"
        params.append(limit)

        rows = self.connection.execute(query, params).fetchall()
        return [
            ActivityEntry(
                event_id=int(row["event_id"]),
                event_name=str(row["event_name"]),
                tx_hash=row["tx_hash"],
                block_height=row["block_height"],
                account_from=row["account_from"],
                account_to=row["account_to"],
                actor=row["actor"],
                amount=row["amount"],
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
            "contract": summary.contract,
            "last_event_id": summary.last_event_id,
            "activity_count": summary.activity_count,
            "tracked_accounts": summary.tracked_accounts,
            "cursors": self.get_cursors(),
        }

    def _upsert_account(
        self,
        address: str,
        *,
        balance_delta: Decimal = ZERO,
        issued_delta: Decimal = ZERO,
        received_delta: Decimal = ZERO,
        sent_delta: Decimal = ZERO,
        burned_delta: Decimal = ZERO,
        event_id: int,
    ) -> None:
        current = self.connection.execute(
            """
            SELECT
                balance,
                issued,
                received,
                sent,
                burned
            FROM account_balances
            WHERE address = ?
            """,
            (address,),
        ).fetchone()
        balance = _to_decimal(current["balance"]) if current is not None else ZERO
        issued = _to_decimal(current["issued"]) if current is not None else ZERO
        received = _to_decimal(current["received"]) if current is not None else ZERO
        sent = _to_decimal(current["sent"]) if current is not None else ZERO
        burned = _to_decimal(current["burned"]) if current is not None else ZERO

        self.connection.execute(
            """
            INSERT INTO account_balances (
                address,
                balance,
                issued,
                received,
                sent,
                burned,
                last_event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(address) DO UPDATE SET
                balance = excluded.balance,
                issued = excluded.issued,
                received = excluded.received,
                sent = excluded.sent,
                burned = excluded.burned,
                last_event_id = excluded.last_event_id
            """,
            (
                address,
                _decimal_to_string(balance + balance_delta),
                _decimal_to_string(issued + issued_delta),
                _decimal_to_string(received + received_delta),
                _decimal_to_string(sent + sent_delta),
                _decimal_to_string(burned + burned_delta),
                event_id,
            ),
        )

    def _update_summary(
        self,
        *,
        issued_delta: Decimal = ZERO,
        burned_delta: Decimal = ZERO,
        transferred_delta: Decimal = ZERO,
        supply_delta: Decimal = ZERO,
        event_id: int,
    ) -> None:
        current = self.connection.execute(
            """
            SELECT
                total_issued,
                total_burned,
                total_transferred,
                projected_supply
            FROM ledger_summary
            WHERE id = 1
            """
        ).fetchone()
        total_issued = _to_decimal(current["total_issued"])
        total_burned = _to_decimal(current["total_burned"])
        total_transferred = _to_decimal(current["total_transferred"])
        projected_supply = _to_decimal(current["projected_supply"])
        self.connection.execute(
            """
            UPDATE ledger_summary
            SET
                total_issued = ?,
                total_burned = ?,
                total_transferred = ?,
                projected_supply = ?,
                last_event_id = ?
            WHERE id = 1
            """,
            (
                _decimal_to_string(total_issued + issued_delta),
                _decimal_to_string(total_burned + burned_delta),
                _decimal_to_string(total_transferred + transferred_delta),
                _decimal_to_string(projected_supply + supply_delta),
                event_id,
            ),
        )

    def _set_cursor(self, event_name: str, event_id: int) -> None:
        if not event_name:
            return
        self.connection.execute(
            """
            INSERT INTO projection_state (name, value)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET value = excluded.value
            """,
            (f"cursor:{event_name}", str(event_id)),
        )
