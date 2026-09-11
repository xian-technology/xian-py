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
        self.uncertain: Reservation | None = None

    async def reserve(self, read_nonce, *, refresh=False):
        async with self.lock:
            if self.next_nonce is None or self.uncertain is not None or refresh:
                network_nonce = await read_nonce()
                if self.uncertain is not None and network_nonce <= self.uncertain.nonce:
                    raise NonceReservationError(
                        "Previous submission is unresolved; reconcile its transaction hash before sending again",
                        details={"nonce": self.uncertain.nonce, "tx_hash": self.uncertain.tx_hash},
                    )
                self.uncertain = None
                self.next_nonce = network_nonce
            nonce = self.next_nonce
            if not refresh:
                self.next_nonce += 1
            return nonce

    def release(self, reservation):
        # Automatic send_lock remains held through this transition.
        self.next_nonce = reservation.nonce

    def reject(self):
        self.next_nonce = None

    def quarantine(self, reservation):
        self.uncertain = reservation
        self.next_nonce = None
