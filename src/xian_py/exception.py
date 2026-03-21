from __future__ import annotations

from typing import Any


class XianException(Exception):
    def __init__(
        self,
        message_or_exception: str | Exception,
        *,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if isinstance(message_or_exception, Exception):
            message = str(message_or_exception)
            cause = cause or message_or_exception
        else:
            message = str(message_or_exception)
        super().__init__(message)
        self.ex_name = (
            type(cause).__name__
            if cause is not None
            else type(message_or_exception).__name__
            if isinstance(message_or_exception, Exception)
            else type(self).__name__
        )
        self.ex_msg = message
        self.ex = cause or (
            message_or_exception
            if isinstance(message_or_exception, Exception)
            else None
        )
        self.details = details or {}


class TransportError(XianException):
    pass


class RpcError(XianException):
    pass


class AbciError(XianException):
    pass


class SimulationError(AbciError):
    pass


class TransactionError(XianException):
    pass


class TxTimeoutError(TransactionError):
    pass
