from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal


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
    chi_margin: float = 0.10
    min_chi_headroom: int = 10


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
