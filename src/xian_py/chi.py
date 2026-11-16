"""The chi a transaction supplies when the caller does not choose it."""

from __future__ import annotations

from xian_py.exception import TransactionError

# Chi added to the simulated estimate. A simulation is exact for the state it
# ran on, but a transaction that lands between simulation and execution can
# change that state: a stored value can grow by a byte, so execution can need
# one chi more than the estimate and would fail with "Out of chi". A paid
# transaction pays half of the chi it leaves unused (rounded down), so the
# margin costs the sender at most one chi.
CHI_ESTIMATE_MARGIN = 2

# The chain's per-transaction chi cap (genesis fee policy ``max_tx_chi``).
# CheckTx refuses a transaction that supplies more.
MAX_TX_CHI = 200_000


def chi_to_supply(estimated: int) -> int:
    """The chi to supply for a call whose simulation used ``estimated`` chi."""
    if estimated > MAX_TX_CHI:
        raise TransactionError(
            f"the simulated cost of {estimated} chi exceeds the per-transaction "
            f"limit of {MAX_TX_CHI} chi"
        )
    return min(estimated + CHI_ESTIMATE_MARGIN, MAX_TX_CHI)
