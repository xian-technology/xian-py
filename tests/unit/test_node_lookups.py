"""Chain id and transaction lookups against CometBFT's real RPC answers.

The fake session answers like a CometBFT 0.39 node: URI-handler errors come
back as HTTP 500 with a JSON-RPC error body (rpc/jsonrpc/server/
http_uri_handler.go), ``/genesis`` refuses documents above 16 MiB
(rpc/core/net.go).
"""

import asyncio
from urllib.parse import urlsplit

from xian_py.xian_async import XianAsync

CHAIN_ID = "xian-launch-1"

GENESIS_TOO_LARGE = {
    "jsonrpc": "2.0",
    "id": -1,
    "error": {
        "code": -32603,
        "message": "Internal error",
        "data": "genesis response is large, please use the genesis_chunked API instead",
    },
}
STATUS = {
    "jsonrpc": "2.0",
    "id": -1,
    "result": {
        "node_info": {"id": "node-1", "network": CHAIN_ID, "moniker": "validator"},
        "sync_info": {"latest_block_height": "12", "catching_up": False},
    },
}


class _CometResponse:
    def __init__(self, status: int, payload: dict):
        self.status = status
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self) -> dict:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")


class _CometSession:
    """Answers by URL path; records every path it was asked for."""

    def __init__(self, routes: dict[str, tuple[int, dict]]):
        self.routes = routes
        self.paths: list[str] = []
        self.closed = False

    def request(self, method: str, url: str, **kwargs) -> _CometResponse:
        path = urlsplit(url).path
        self.paths.append(path)
        status, payload = self.routes[path]
        return _CometResponse(status, payload)

    async def close(self) -> None:
        self.closed = True


def _node(**extra: tuple[int, dict]) -> _CometSession:
    return _CometSession({"/genesis": (500, GENESIS_TOO_LARGE), "/status": (200, STATUS), **extra})


def _run(coro_factory):
    async def runner():
        return await coro_factory()

    return asyncio.run(runner())


def test_chain_id_comes_from_status_when_genesis_is_too_large() -> None:
    session = _node()

    async def lookup():
        client = XianAsync("http://node", session=session)
        await client.ensure_chain_id()
        await client.ensure_chain_id()
        return client.chain_id

    assert _run(lookup) == CHAIN_ID
    assert session.paths == ["/status"]
