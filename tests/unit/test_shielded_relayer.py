from __future__ import annotations

import asyncio
import json

from xian_py.exception import XianException
from xian_py.models import (
    ShieldedRelayerInfo,
    ShieldedRelayerJob,
    ShieldedRelayerJobResult,
    ShieldedRelayerQuote,
    ShieldedRelayerQuoteResult,
)
from xian_py.shielded_relayer import (
    ShieldedRelayerAsyncClient,
    ShieldedRelayerAsyncPoolClient,
)


class _FakeResponse:
    def __init__(self, payload: dict, *, status: int = 200):
        self._payload = payload
        self.status = status
        self.ok = 200 <= status < 300

    async def json(self) -> dict:
        return self._payload

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeSession:
    def __init__(
        self,
        responses: list[_FakeResponse] | None = None,
        *,
        handler=None,
    ):
        self._responses = list(responses or [])
        self._handler = handler
        self.requests: list[tuple[str, str, dict]] = []
        self.closed = False

    def request(self, method: str, url: str, **kwargs):
        self.requests.append((method, url, kwargs))
        if self._handler is not None:
            return self._handler(method, url, kwargs)
        return self._responses.pop(0)

    async def close(self) -> None:
        self.closed = True


def test_async_relayer_client_reads_info_and_quote() -> None:
    async def run() -> None:
        session = _FakeSession(
            [
                _FakeResponse(
                    {
                        "service": "xian-shielded-relayer",
                        "protocol_version": "v1",
                        "available": True,
                        "chain_id": "xian-testnet-1",
                        "relayer_account": "abcd",
                        "submission_mode": "checktx",
                        "wait_for_tx": True,
                        "capabilities": {
                            "shielded_note_relay_transfer": True,
                            "shielded_command": True,
                        },
                        "policy": {
                            "quote_ttl_seconds": 30,
                            "default_expiry_seconds": 120,
                            "max_expiry_seconds": 600,
                            "min_note_relayer_fee": 1,
                            "min_command_relayer_fee": 2,
                            "allowed_note_contracts": ["con_private_usd"],
                            "allowed_command_contracts": [
                                "con_shielded_commands"
                            ],
                            "allowed_command_targets": ["con_dex"],
                        },
                    }
                ),
                _FakeResponse(
                    {
                        "kind": "shielded_note_relay_transfer",
                        "contract": "con_private_usd",
                        "target_contract": None,
                        "chain_id": "xian-testnet-1",
                        "relayer_account": "abcd",
                        "relayer_fee": 2,
                        "expires_at": "2026-04-10 12:00:00",
                        "issued_at": "2026-04-10 11:58:00",
                        "policy_version": "v1",
                    }
                ),
            ]
        )
        client = ShieldedRelayerAsyncClient(
            "http://127.0.0.1:38888/",
            auth_token="secret",
            session=session,
        )

        info = await client.get_info()
        quote = await client.get_quote(
            kind="shielded_note_relay_transfer",
            contract="con_private_usd",
            requested_relayer_fee=2,
            requested_expires_in_seconds=90,
        )

        assert isinstance(info, ShieldedRelayerInfo)
        assert info.chain_id == "xian-testnet-1"
        assert info.policy.allowed_note_contracts == ["con_private_usd"]
        assert isinstance(quote, ShieldedRelayerQuote)
        assert quote.relayer_fee == 2
        assert session.requests[0][1] == "http://127.0.0.1:38888/v1/info"
        assert (
            session.requests[0][2]["headers"]["Authorization"]
            == "Bearer secret"
        )
        assert json.dumps(
            session.requests[1][2]["json"], sort_keys=True
        ) == json.dumps(
            {
                "kind": "shielded_note_relay_transfer",
                "contract": "con_private_usd",
                "target_contract": None,
                "requested_relayer_fee": 2,
                "requested_expires_in_seconds": 90,
            },
            sort_keys=True,
        )

    asyncio.run(run())


def test_async_relayer_client_submits_and_reads_job() -> None:
    async def run() -> None:
        session = _FakeSession(
            [
                _FakeResponse(
                    {
                        "job_id": "job-1",
                        "kind": "shielded_command",
                        "status": "finalized",
                        "chain_id": "xian-testnet-1",
                        "relayer_account": "abcd",
                        "contract": "con_shielded_commands",
                        "function_name": "execute_command",
                        "tx_hash": "ABC123",
                        "submitted_at": "2026-04-10T10:00:00Z",
                        "updated_at": "2026-04-10T10:00:05Z",
                        "error": None,
                        "submission": {
                            "submitted": True,
                            "accepted": True,
                            "finalized": True,
                            "tx_hash": "ABC123",
                            "mode": "checktx",
                            "nonce": 7,
                            "chi_supplied": 12345,
                            "chi_estimated": 12000,
                            "message": None,
                            "response": {"result": {"hash": "ABC123"}},
                            "receipt": {
                                "success": True,
                                "tx_hash": "ABC123",
                                "message": None,
                                "transaction": {"payload": {}},
                                "execution": {"events": []},
                                "raw": {"success": True},
                            },
                        },
                    }
                ),
                _FakeResponse(
                    {
                        "job_id": "job-1",
                        "kind": "shielded_command",
                        "status": "finalized",
                    }
                ),
            ]
        )
        client = ShieldedRelayerAsyncClient(
            "http://127.0.0.1:38888", session=session
        )

        job = await client.submit_shielded_command(
            contract="con_shielded_commands",
            target_contract="con_dex",
            old_root="0xroot",
            input_nullifiers=["0x1"],
            output_commitments=["0x2"],
            proof_hex="0xproof",
            relayer_fee=5,
            public_amount=10,
            payload={"action": "swap"},
            expires_at="2026-04-10 12:00:00",
            output_payloads=["0xpayload"],
            client_request_id="client-1",
        )
        fetched = await client.get_job("job-1")

        assert isinstance(job, ShieldedRelayerJob)
        assert job.tx_hash == "ABC123"
        assert job.submission is not None
        assert job.submission.receipt is not None
        assert fetched.job_id == "job-1"

    asyncio.run(run())


def test_async_relayer_client_does_not_close_caller_owned_session() -> None:
    async def run() -> None:
        session = _FakeSession(
            [
                _FakeResponse(
                    {
                        "service": "xian-shielded-relayer",
                        "protocol_version": "v1",
                        "available": True,
                        "chain_id": "xian-testnet-1",
                        "relayer_account": "abcd",
                        "submission_mode": "checktx",
                        "wait_for_tx": True,
                        "capabilities": {
                            "shielded_note_relay_transfer": True,
                            "shielded_command": True,
                        },
                        "policy": {
                            "quote_ttl_seconds": 30,
                            "default_expiry_seconds": 120,
                            "max_expiry_seconds": 600,
                            "min_note_relayer_fee": 1,
                            "min_command_relayer_fee": 2,
                            "allowed_note_contracts": ["con_private_usd"],
                            "allowed_command_contracts": [
                                "con_shielded_commands"
                            ],
                            "allowed_command_targets": ["con_dex"],
                        },
                    }
                ),
                _FakeResponse(
                    {
                        "service": "xian-shielded-relayer",
                        "protocol_version": "v1",
                        "available": True,
                        "chain_id": "xian-testnet-1",
                        "relayer_account": "abcd",
                        "submission_mode": "checktx",
                        "wait_for_tx": True,
                        "capabilities": {
                            "shielded_note_relay_transfer": True,
                            "shielded_command": True,
                        },
                        "policy": {
                            "quote_ttl_seconds": 30,
                            "default_expiry_seconds": 120,
                            "max_expiry_seconds": 600,
                            "min_note_relayer_fee": 1,
                            "min_command_relayer_fee": 2,
                            "allowed_note_contracts": ["con_private_usd"],
                            "allowed_command_contracts": [
                                "con_shielded_commands"
                            ],
                            "allowed_command_targets": ["con_dex"],
                        },
                    }
                ),
            ]
        )

        async with ShieldedRelayerAsyncClient(
            "http://127.0.0.1:38888",
            session=session,
        ) as client:
            await client.get_info()

        assert session.closed is False

        follow_up = ShieldedRelayerAsyncClient(
            "http://127.0.0.1:38888",
            session=session,
        )
        await follow_up.get_info()
        assert session.closed is False

    asyncio.run(run())


def test_async_relayer_pool_client_fails_over_quote_requests() -> None:
    async def run() -> None:
        def handler(method: str, url: str, kwargs: dict) -> _FakeResponse:
            assert method == "POST"
            if url == "http://relayer-a/v1/quote":
                raise RuntimeError("relayer-a unavailable")
            if url == "http://relayer-b/v1/quote":
                return _FakeResponse(
                    {
                        "kind": "shielded_note_relay_transfer",
                        "contract": "con_private_usd",
                        "target_contract": None,
                        "chain_id": "xian-testnet-1",
                        "relayer_account": "abcd",
                        "relayer_fee": 4,
                        "expires_at": "2026-04-10 12:00:00",
                        "issued_at": "2026-04-10 11:58:00",
                        "policy_version": "v1",
                    }
                )
            raise AssertionError(f"unexpected URL {url} with {kwargs}")

        pool = ShieldedRelayerAsyncPoolClient(
            [
                {
                    "id": "relayer-b",
                    "relayer_url": "http://relayer-b",
                    "priority": 20,
                    "submission_kinds": ["shielded_note_relay_transfer"],
                },
                {
                    "id": "relayer-a",
                    "relayer_url": "http://relayer-a",
                    "priority": 10,
                    "submission_kinds": ["shielded_note_relay_transfer"],
                },
            ],
            session=_FakeSession(handler=handler),
        )

        result = await pool.get_quote(
            kind="shielded_note_relay_transfer",
            contract="con_private_usd",
        )

        assert isinstance(result, ShieldedRelayerQuoteResult)
        assert result.relayer.id == "relayer-b"
        assert result.quote.relayer_fee == 4

    asyncio.run(run())


def test_async_relayer_pool_client_does_not_close_caller_owned_session() -> None:
    async def run() -> None:
        session = _FakeSession(
            [
                _FakeResponse(
                    {
                        "service": "xian-shielded-relayer",
                        "protocol_version": "v1",
                        "available": True,
                        "chain_id": "xian-testnet-1",
                        "relayer_account": "abcd",
                        "submission_mode": "checktx",
                        "wait_for_tx": True,
                        "capabilities": {
                            "shielded_note_relay_transfer": True,
                            "shielded_command": True,
                        },
                        "policy": {
                            "quote_ttl_seconds": 30,
                            "default_expiry_seconds": 120,
                            "max_expiry_seconds": 600,
                            "min_note_relayer_fee": 1,
                            "min_command_relayer_fee": 2,
                            "allowed_note_contracts": ["con_private_usd"],
                            "allowed_command_contracts": [
                                "con_shielded_commands"
                            ],
                            "allowed_command_targets": ["con_dex"],
                        },
                    }
                ),
                _FakeResponse(
                    {
                        "service": "xian-shielded-relayer",
                        "protocol_version": "v1",
                        "available": True,
                        "chain_id": "xian-testnet-1",
                        "relayer_account": "abcd",
                        "submission_mode": "checktx",
                        "wait_for_tx": True,
                        "capabilities": {
                            "shielded_note_relay_transfer": True,
                            "shielded_command": True,
                        },
                        "policy": {
                            "quote_ttl_seconds": 30,
                            "default_expiry_seconds": 120,
                            "max_expiry_seconds": 600,
                            "min_note_relayer_fee": 1,
                            "min_command_relayer_fee": 2,
                            "allowed_note_contracts": ["con_private_usd"],
                            "allowed_command_contracts": [
                                "con_shielded_commands"
                            ],
                            "allowed_command_targets": ["con_dex"],
                        },
                    }
                ),
            ]
        )
        pool = ShieldedRelayerAsyncPoolClient(
            [
                {
                    "id": "relayer-a",
                    "relayer_url": "http://127.0.0.1:38888",
                    "submission_kinds": ["shielded_note_relay_transfer"],
                }
            ],
            session=session,
        )

        async with pool:
            await pool.get_info(relayer_id="relayer-a")

        assert session.closed is False

        await pool.get_info(relayer_id="relayer-a")
        assert session.closed is False

    asyncio.run(run())


def test_async_relayer_pool_client_requires_explicit_routing_for_submit() -> (
    None
):
    async def run() -> None:
        pool = ShieldedRelayerAsyncPoolClient(
            [
                {
                    "id": "relayer-a",
                    "relayer_url": "http://relayer-a",
                    "submission_kinds": ["shielded_command"],
                },
                {
                    "id": "relayer-b",
                    "relayer_url": "http://relayer-b",
                    "submission_kinds": ["shielded_command"],
                },
            ]
        )

        try:
            await pool.submit_shielded_command(
                contract="con_shielded_commands",
                target_contract="con_dex",
                old_root="0xroot",
                input_nullifiers=["0x1"],
                output_commitments=["0x2"],
                proof_hex="0xproof",
                relayer_fee=5,
            )
        except XianException as exc:
            assert (
                str(exc) == "submit_shielded_command requires relayer_id when "
                "multiple shielded relayers are configured"
            )
        else:
            raise AssertionError("expected submit to require relayer_id")

    asyncio.run(run())


def test_async_relayer_pool_client_routes_single_submit_without_relayer_id() -> (
    None
):
    async def run() -> None:
        session = _FakeSession(
            handler=lambda method, url, kwargs: _FakeResponse(
                {
                    "job_id": "job-2",
                    "kind": "shielded_command",
                    "status": "accepted",
                    "chain_id": "xian-testnet-1",
                    "relayer_account": "abcd",
                    "contract": "con_shielded_commands",
                    "function_name": "execute_command",
                    "tx_hash": "DEF456",
                    "submitted_at": "2026-04-10T10:00:00Z",
                    "updated_at": "2026-04-10T10:00:05Z",
                    "error": None,
                    "submission": {
                        "submitted": True,
                        "accepted": True,
                        "finalized": False,
                        "tx_hash": "DEF456",
                        "mode": "checktx",
                        "nonce": 9,
                        "chi_supplied": 123,
                        "chi_estimated": 120,
                        "message": None,
                        "response": {"result": {"hash": "DEF456"}},
                    },
                }
                if method == "POST"
                and url == "http://relayer-only/v1/jobs/shielded-command"
                else (_ for _ in ()).throw(
                    AssertionError(f"unexpected URL {url} with {kwargs}")
                )
            )
        )
        pool = ShieldedRelayerAsyncPoolClient(
            [
                {
                    "id": "relayer-only",
                    "relayer_url": "http://relayer-only",
                    "submission_kinds": ["shielded_command"],
                }
            ],
            session=session,
        )

        result = await pool.submit_shielded_command(
            contract="con_shielded_commands",
            target_contract="con_dex",
            old_root="0xroot",
            input_nullifiers=["0x1"],
            output_commitments=["0x2"],
            proof_hex="0xproof",
            relayer_fee=5,
        )

        assert isinstance(result, ShieldedRelayerJobResult)
        assert result.relayer.id == "relayer-only"
        assert result.job.job_id == "job-2"

    asyncio.run(run())
