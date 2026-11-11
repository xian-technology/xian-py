from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal

DEFAULT_VM_PROFILE: Literal["xian_vm_v2"] = "xian_vm_v2"
# Shared with xian-js: supply estimate + max(ceil(estimate * 5%), 10) chi.
# Simulated cost can drift before execution; unused chi is refunded.
DEFAULT_CHI_MARGIN = 0.05
DEFAULT_MIN_CHI_HEADROOM = 10


def _validate_chi_headroom(chi_margin: float, min_chi_headroom: int) -> None:
    if not isinstance(chi_margin, (int, float)) or isinstance(chi_margin, bool):
        raise ValueError("chi_margin must be a finite non-negative number")
    if not math.isfinite(chi_margin) or chi_margin < 0:
        raise ValueError("chi_margin must be a finite non-negative number")
    if type(min_chi_headroom) is not int or min_chi_headroom < 0:
        raise ValueError("min_chi_headroom must be a non-negative integer")


def suggest_chi_supplied(estimated: int, *, chi_margin: float, min_chi_headroom: int) -> int:
    """Return the chi to supply for a simulated ``estimated`` cost."""
    _validate_chi_headroom(chi_margin, min_chi_headroom)
    if type(estimated) is not int or estimated < 0:
        raise ValueError("estimated chi must be a non-negative integer")
    return estimated + max(math.ceil(estimated * chi_margin), min_chi_headroom)


@dataclass(frozen=True)
class TransportConfig:
    total_timeout_seconds: float = 15.0
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 10.0
    connection_limit: int = 100
    dns_cache_ttl_seconds: int = 300


@dataclass(frozen=True)
class RetryEvent:
    operation: Literal["read", "broadcast"]
    attempt: int
    max_attempts: int
    next_delay_seconds: float
    error: Exception


RetryCallback = Callable[[RetryEvent], object | Awaitable[object]]


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_delay_seconds: float = 0.25
    max_delay_seconds: float = 2.0
    backoff_multiplier: float = 2.0
    retry_transport_errors: bool = True
    retry_rpc_errors: bool = False
    on_retry: RetryCallback | None = None


@dataclass(frozen=True)
class SubmissionConfig:
    mode: Literal["async", "checktx", "commit"] = "checktx"
    wait_for_tx: bool = False
    timeout_seconds: float = 30.0
    poll_interval_seconds: float = 0.25
    chi_margin: float = DEFAULT_CHI_MARGIN
    min_chi_headroom: int = DEFAULT_MIN_CHI_HEADROOM

    def __post_init__(self):
        _validate_chi_headroom(self.chi_margin, self.min_chi_headroom)


@dataclass(frozen=True)
class WatcherConfig:
    mode: Literal["auto", "poll", "websocket"] = "auto"
    poll_interval_seconds: float = 1.0
    batch_limit: int = 100
    websocket_url: str | None = None
    websocket_heartbeat_seconds: float = 25.0


@dataclass(frozen=True)
class XianClientConfig:
    transport: TransportConfig = field(default_factory=TransportConfig)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    submission: SubmissionConfig = field(default_factory=SubmissionConfig)
    watcher: WatcherConfig = field(default_factory=WatcherConfig)
    vm_profile: Literal["xian_vm_v1", "xian_vm_v2"] = DEFAULT_VM_PROFILE

    def __post_init__(self):
        if self.vm_profile not in ("xian_vm_v1", "xian_vm_v2"):
            raise ValueError(f"Unsupported VM profile: {self.vm_profile}")
