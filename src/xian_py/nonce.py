"""Per-chain/account coordination for automatic transaction submission."""

import asyncio
from dataclasses import dataclass

from xian_py.exception import NonceReservationError


@dataclass
class Reservation:
    nonce: int | None = None
    tx_hash: str | None = None
    broadcast_started: bool = False


class NonceState:
    def __init__(self):
        self.send_lock = asyncio.Lock()
        self.lock = asyncio.Lock()
        self.next_nonce: int | None = None
        self.refresh_required = False
        self.uncertain: Reservation | None = None

    async def reserve(self, read_nonce, *, refresh=False):
        async with self.lock:
            if self.next_nonce is None or self.refresh_required or refresh:
                network_nonce = await read_nonce()
                if self.uncertain is not None and network_nonce <= self.uncertain.nonce:
                    raise NonceReservationError(
                        "Previous submission is unresolved; reconcile its transaction hash before sending again",
                        details={"nonce": self.uncertain.nonce, "tx_hash": self.uncertain.tx_hash},
                    )
                self.uncertain = None
                self.next_nonce = max(network_nonce, self.next_nonce or 0)
                self.refresh_required = False
            nonce = self.next_nonce
            if not refresh:
                self.next_nonce += 1
            return nonce

    def release(self, reservation):
        # Automatic send_lock remains held through this transition.
        self.next_nonce = reservation.nonce

    def reject(self, reservation):
        self.release(reservation)
        self.refresh_required = True

    def quarantine(self, reservation):
        self.uncertain = reservation
        self.next_nonce = None
