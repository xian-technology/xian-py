from __future__ import annotations

from typing import Any, Callable, Mapping

import aiohttp

from xian_py.exception import TransportError, XianException
from xian_py.models import (
    ShieldedRelayerCatalogEntry,
    ShieldedRelayerInfo,
    ShieldedRelayerInfoResult,
    ShieldedRelayerJob,
    ShieldedRelayerJobResult,
    ShieldedRelayerQuote,
    ShieldedRelayerQuoteResult,
)
from xian_py.run_sync import run_sync


def _strip_trailing_slash(value: str) -> str:
    return value.rstrip("/")


def _normalize_relayer_catalog(
    relayers: list[ShieldedRelayerCatalogEntry | Mapping[str, Any]],
) -> list[ShieldedRelayerCatalogEntry]:
    normalized: list[ShieldedRelayerCatalogEntry] = []
    for index, relayer in enumerate(relayers):
        entry = (
            relayer
            if isinstance(relayer, ShieldedRelayerCatalogEntry)
            else ShieldedRelayerCatalogEntry.from_dict(relayer, index=index)
        )
        normalized.append(entry)
    normalized.sort(
        key=lambda entry: (entry.priority, entry.id, entry.relayer_url)
    )
    seen: set[str] = set()
    for entry in normalized:
        if entry.id in seen:
            raise XianException(f"duplicate shielded relayer id: {entry.id}")
        seen.add(entry.id)
    return normalized


def _supports_kind(relayer: ShieldedRelayerCatalogEntry, kind: str) -> bool:
    return kind in relayer.submission_kinds


def _build_aggregate_transport_error(
    action: str,
    failures: list[tuple[ShieldedRelayerCatalogEntry, Exception]],
) -> TransportError:
    detail = "; ".join(f"{relayer.id}: {error}" for relayer, error in failures)
    return TransportError(
        f"{action} failed for all candidate relayers: {detail}"
    )


class ShieldedRelayerAsyncClient:
    def __init__(
        self,
        relayer_url: str,
        *,
        auth_token: str | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.relayer_url = _strip_trailing_slash(relayer_url)
        self.auth_token = auth_token.strip() if auth_token else None
        self._session = session

    async def __aenter__(self) -> "ShieldedRelayerAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        request_kwargs: dict[str, Any] = {"headers": headers}
        if body is not None:
            request_kwargs["json"] = dict(body)

        try:
            async with self.session.request(
                method,
                f"{self.relayer_url}{path}",
                **request_kwargs,
            ) as response:
                data = await response.json()
                if not response.ok:
                    message = (
                        data.get("error")
                        if isinstance(data, Mapping)
                        else f"relayer request failed with status {response.status}"
                    )
                    raise TransportError(message)
        except TransportError:
            raise
        except Exception as exc:
            raise TransportError(exc) from exc

        if not isinstance(data, Mapping):
            raise TransportError("expected object response")
        return dict(data)

    async def get_info(self) -> ShieldedRelayerInfo:
        return ShieldedRelayerInfo.from_dict(
            await self._request_json("GET", "/v1/info")
        )

    async def get_quote(
        self,
        *,
        kind: str,
        contract: str,
        target_contract: str | None = None,
        requested_relayer_fee: int | None = None,
        requested_expires_in_seconds: int | None = None,
    ) -> ShieldedRelayerQuote:
        return ShieldedRelayerQuote.from_dict(
            await self._request_json(
                "POST",
                "/v1/quote",
                body={
                    "kind": kind,
                    "contract": contract,
                    "target_contract": target_contract,
                    "requested_relayer_fee": requested_relayer_fee,
                    "requested_expires_in_seconds": requested_expires_in_seconds,
                },
            )
        )

    async def submit_shielded_note_relay_transfer(
        self,
        *,
        contract: str,
        old_root: str,
        input_nullifiers: list[str],
        output_commitments: list[str],
        proof_hex: str,
        relayer_fee: int,
        expires_at: str | None = None,
        output_payloads: list[str] | None = None,
        client_request_id: str | None = None,
    ) -> ShieldedRelayerJob:
        return ShieldedRelayerJob.from_dict(
            await self._request_json(
                "POST",
                "/v1/jobs/shielded-note-transfer",
                body={
                    "contract": contract,
                    "old_root": old_root,
                    "input_nullifiers": input_nullifiers,
                    "output_commitments": output_commitments,
                    "proof_hex": proof_hex,
                    "relayer_fee": relayer_fee,
                    "expires_at": expires_at,
                    "output_payloads": list(output_payloads or []),
                    "client_request_id": client_request_id,
                },
            )
        )

    async def submit_shielded_command(
        self,
        *,
        contract: str,
        target_contract: str,
        old_root: str,
        input_nullifiers: list[str],
        output_commitments: list[str],
        proof_hex: str,
        relayer_fee: int,
        public_amount: int = 0,
        payload: dict[str, Any] | None = None,
        expires_at: str | None = None,
        output_payloads: list[str] | None = None,
        client_request_id: str | None = None,
    ) -> ShieldedRelayerJob:
        return ShieldedRelayerJob.from_dict(
            await self._request_json(
                "POST",
                "/v1/jobs/shielded-command",
                body={
                    "contract": contract,
                    "target_contract": target_contract,
                    "old_root": old_root,
                    "input_nullifiers": input_nullifiers,
                    "output_commitments": output_commitments,
                    "proof_hex": proof_hex,
                    "relayer_fee": relayer_fee,
                    "public_amount": public_amount,
                    "payload": payload,
                    "expires_at": expires_at,
                    "output_payloads": list(output_payloads or []),
                    "client_request_id": client_request_id,
                },
            )
        )

    async def get_job(self, job_id: str) -> ShieldedRelayerJob:
        return ShieldedRelayerJob.from_dict(
            await self._request_json("GET", f"/v1/jobs/{job_id}")
        )


class ShieldedRelayerAsyncPoolClient:
    def __init__(
        self,
        relayers: list[ShieldedRelayerCatalogEntry | Mapping[str, Any]],
        *,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._relayers = _normalize_relayer_catalog(relayers)
        if not self._relayers:
            raise XianException(
                "shielded relayer pool requires at least one configured relayer"
            )
        self._clients = {
            relayer.id: ShieldedRelayerAsyncClient(
                relayer.relayer_url,
                auth_token=relayer.auth_token,
                session=session,
            )
            for relayer in self._relayers
        }

    async def __aenter__(self) -> "ShieldedRelayerAsyncPoolClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        for client in self._clients.values():
            await client.close()

    def list_relayers(
        self, kind: str | None = None
    ) -> list[ShieldedRelayerCatalogEntry]:
        relayers = (
            self._relayers
            if kind is None
            else [
                relayer
                for relayer in self._relayers
                if _supports_kind(relayer, kind)
            ]
        )
        return list(relayers)

    def get_client(self, relayer_id: str) -> ShieldedRelayerAsyncClient:
        client = self._clients.get(relayer_id)
        if client is None:
            raise XianException(f"unknown shielded relayer id: {relayer_id}")
        return client

    async def get_info(
        self, *, relayer_id: str | None = None
    ) -> ShieldedRelayerInfoResult:
        candidates = self._select_candidates(relayer_id=relayer_id)

        async def load(
            relayer: ShieldedRelayerCatalogEntry,
        ) -> ShieldedRelayerInfoResult:
            return ShieldedRelayerInfoResult(
                relayer=relayer,
                info=await self.get_client(relayer.id).get_info(),
            )

        return await self._resolve_with_failover("get_info", candidates, load)

    async def get_quote(
        self,
        *,
        kind: str,
        contract: str,
        target_contract: str | None = None,
        requested_relayer_fee: int | None = None,
        requested_expires_in_seconds: int | None = None,
        relayer_id: str | None = None,
    ) -> ShieldedRelayerQuoteResult:
        candidates = self._select_candidates(kind=kind, relayer_id=relayer_id)

        async def load(
            relayer: ShieldedRelayerCatalogEntry,
        ) -> ShieldedRelayerQuoteResult:
            return ShieldedRelayerQuoteResult(
                relayer=relayer,
                quote=await self.get_client(relayer.id).get_quote(
                    kind=kind,
                    contract=contract,
                    target_contract=target_contract,
                    requested_relayer_fee=requested_relayer_fee,
                    requested_expires_in_seconds=requested_expires_in_seconds,
                ),
            )

        return await self._resolve_with_failover("get_quote", candidates, load)

    async def submit_shielded_note_relay_transfer(
        self,
        *,
        contract: str,
        old_root: str,
        input_nullifiers: list[str],
        output_commitments: list[str],
        proof_hex: str,
        relayer_fee: int,
        expires_at: str | None = None,
        output_payloads: list[str] | None = None,
        client_request_id: str | None = None,
        relayer_id: str | None = None,
    ) -> ShieldedRelayerJobResult:
        relayer = self._resolve_submission_relayer(
            "submit_shielded_note_relay_transfer",
            kind="shielded_note_relay_transfer",
            relayer_id=relayer_id,
        )
        return ShieldedRelayerJobResult(
            relayer=relayer,
            job=await self.get_client(
                relayer.id
            ).submit_shielded_note_relay_transfer(
                contract=contract,
                old_root=old_root,
                input_nullifiers=input_nullifiers,
                output_commitments=output_commitments,
                proof_hex=proof_hex,
                relayer_fee=relayer_fee,
                expires_at=expires_at,
                output_payloads=output_payloads,
                client_request_id=client_request_id,
            ),
        )

    async def submit_shielded_command(
        self,
        *,
        contract: str,
        target_contract: str,
        old_root: str,
        input_nullifiers: list[str],
        output_commitments: list[str],
        proof_hex: str,
        relayer_fee: int,
        public_amount: int = 0,
        payload: dict[str, Any] | None = None,
        expires_at: str | None = None,
        output_payloads: list[str] | None = None,
        client_request_id: str | None = None,
        relayer_id: str | None = None,
    ) -> ShieldedRelayerJobResult:
        relayer = self._resolve_submission_relayer(
            "submit_shielded_command",
            kind="shielded_command",
            relayer_id=relayer_id,
        )
        return ShieldedRelayerJobResult(
            relayer=relayer,
            job=await self.get_client(relayer.id).submit_shielded_command(
                contract=contract,
                target_contract=target_contract,
                old_root=old_root,
                input_nullifiers=input_nullifiers,
                output_commitments=output_commitments,
                proof_hex=proof_hex,
                relayer_fee=relayer_fee,
                public_amount=public_amount,
                payload=payload,
                expires_at=expires_at,
                output_payloads=output_payloads,
                client_request_id=client_request_id,
            ),
        )

    async def get_job(
        self, job_id: str, *, relayer_id: str | None = None
    ) -> ShieldedRelayerJobResult:
        relayer = self._resolve_job_relayer("get_job", relayer_id=relayer_id)
        return ShieldedRelayerJobResult(
            relayer=relayer,
            job=await self.get_client(relayer.id).get_job(job_id),
        )

    def _select_candidates(
        self, *, kind: str | None = None, relayer_id: str | None = None
    ) -> list[ShieldedRelayerCatalogEntry]:
        if relayer_id is not None:
            relayer = self._lookup_relayer(relayer_id)
            if kind is not None and not _supports_kind(relayer, kind):
                raise XianException(
                    f"shielded relayer {relayer.id} does not support {kind}"
                )
            return [relayer]
        relayers = self.list_relayers(kind)
        if relayers:
            return relayers
        if kind is None:
            raise XianException("no shielded relayers are configured")
        raise XianException(f"no shielded relayers are configured for {kind}")

    def _resolve_submission_relayer(
        self, action: str, *, kind: str, relayer_id: str | None = None
    ) -> ShieldedRelayerCatalogEntry:
        candidates = self._select_candidates(kind=kind, relayer_id=relayer_id)
        if relayer_id is not None or len(candidates) == 1:
            return candidates[0]
        raise XianException(
            f"{action} requires relayer_id when multiple "
            "shielded relayers are configured"
        )

    def _resolve_job_relayer(
        self, action: str, *, relayer_id: str | None = None
    ) -> ShieldedRelayerCatalogEntry:
        candidates = self._select_candidates(relayer_id=relayer_id)
        if relayer_id is not None or len(candidates) == 1:
            return candidates[0]
        raise XianException(
            f"{action} requires relayer_id when multiple "
            "shielded relayers are configured"
        )

    def _lookup_relayer(self, relayer_id: str) -> ShieldedRelayerCatalogEntry:
        for relayer in self._relayers:
            if relayer.id == relayer_id:
                return relayer
        raise XianException(f"unknown shielded relayer id: {relayer_id}")

    async def _resolve_with_failover(
        self,
        action: str,
        candidates: list[ShieldedRelayerCatalogEntry],
        load: Callable[[ShieldedRelayerCatalogEntry], Any],
    ) -> Any:
        failures: list[tuple[ShieldedRelayerCatalogEntry, Exception]] = []
        for relayer in candidates:
            try:
                return await load(relayer)
            except Exception as exc:
                failures.append((relayer, exc))
        raise _build_aggregate_transport_error(action, failures)


class ShieldedRelayerClient:
    def __init__(
        self,
        relayer_url: str,
        *,
        auth_token: str | None = None,
    ) -> None:
        self._async_client = ShieldedRelayerAsyncClient(
            relayer_url,
            auth_token=auth_token,
        )

    def close(self) -> None:
        run_sync(self._async_client.close())

    def __enter__(self) -> "ShieldedRelayerClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def get_info(self) -> ShieldedRelayerInfo:
        return run_sync(self._async_client.get_info())

    def get_quote(
        self,
        *,
        kind: str,
        contract: str,
        target_contract: str | None = None,
        requested_relayer_fee: int | None = None,
        requested_expires_in_seconds: int | None = None,
    ) -> ShieldedRelayerQuote:
        return run_sync(
            self._async_client.get_quote(
                kind=kind,
                contract=contract,
                target_contract=target_contract,
                requested_relayer_fee=requested_relayer_fee,
                requested_expires_in_seconds=requested_expires_in_seconds,
            )
        )

    def submit_shielded_note_relay_transfer(
        self,
        *,
        contract: str,
        old_root: str,
        input_nullifiers: list[str],
        output_commitments: list[str],
        proof_hex: str,
        relayer_fee: int,
        expires_at: str | None = None,
        output_payloads: list[str] | None = None,
        client_request_id: str | None = None,
    ) -> ShieldedRelayerJob:
        return run_sync(
            self._async_client.submit_shielded_note_relay_transfer(
                contract=contract,
                old_root=old_root,
                input_nullifiers=input_nullifiers,
                output_commitments=output_commitments,
                proof_hex=proof_hex,
                relayer_fee=relayer_fee,
                expires_at=expires_at,
                output_payloads=output_payloads,
                client_request_id=client_request_id,
            )
        )

    def submit_shielded_command(
        self,
        *,
        contract: str,
        target_contract: str,
        old_root: str,
        input_nullifiers: list[str],
        output_commitments: list[str],
        proof_hex: str,
        relayer_fee: int,
        public_amount: int = 0,
        payload: dict[str, Any] | None = None,
        expires_at: str | None = None,
        output_payloads: list[str] | None = None,
        client_request_id: str | None = None,
    ) -> ShieldedRelayerJob:
        return run_sync(
            self._async_client.submit_shielded_command(
                contract=contract,
                target_contract=target_contract,
                old_root=old_root,
                input_nullifiers=input_nullifiers,
                output_commitments=output_commitments,
                proof_hex=proof_hex,
                relayer_fee=relayer_fee,
                public_amount=public_amount,
                payload=payload,
                expires_at=expires_at,
                output_payloads=output_payloads,
                client_request_id=client_request_id,
            )
        )

    def get_job(self, job_id: str) -> ShieldedRelayerJob:
        return run_sync(self._async_client.get_job(job_id))


class ShieldedRelayerPoolClient:
    def __init__(
        self,
        relayers: list[ShieldedRelayerCatalogEntry | Mapping[str, Any]],
    ) -> None:
        self._async_client = ShieldedRelayerAsyncPoolClient(relayers)

    def close(self) -> None:
        run_sync(self._async_client.close())

    def __enter__(self) -> "ShieldedRelayerPoolClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def list_relayers(
        self, kind: str | None = None
    ) -> list[ShieldedRelayerCatalogEntry]:
        return self._async_client.list_relayers(kind)

    def get_info(
        self, *, relayer_id: str | None = None
    ) -> ShieldedRelayerInfoResult:
        return run_sync(self._async_client.get_info(relayer_id=relayer_id))

    def get_quote(
        self,
        *,
        kind: str,
        contract: str,
        target_contract: str | None = None,
        requested_relayer_fee: int | None = None,
        requested_expires_in_seconds: int | None = None,
        relayer_id: str | None = None,
    ) -> ShieldedRelayerQuoteResult:
        return run_sync(
            self._async_client.get_quote(
                kind=kind,
                contract=contract,
                target_contract=target_contract,
                requested_relayer_fee=requested_relayer_fee,
                requested_expires_in_seconds=requested_expires_in_seconds,
                relayer_id=relayer_id,
            )
        )

    def submit_shielded_note_relay_transfer(
        self,
        *,
        contract: str,
        old_root: str,
        input_nullifiers: list[str],
        output_commitments: list[str],
        proof_hex: str,
        relayer_fee: int,
        expires_at: str | None = None,
        output_payloads: list[str] | None = None,
        client_request_id: str | None = None,
        relayer_id: str | None = None,
    ) -> ShieldedRelayerJobResult:
        return run_sync(
            self._async_client.submit_shielded_note_relay_transfer(
                contract=contract,
                old_root=old_root,
                input_nullifiers=input_nullifiers,
                output_commitments=output_commitments,
                proof_hex=proof_hex,
                relayer_fee=relayer_fee,
                expires_at=expires_at,
                output_payloads=output_payloads,
                client_request_id=client_request_id,
                relayer_id=relayer_id,
            )
        )

    def submit_shielded_command(
        self,
        *,
        contract: str,
        target_contract: str,
        old_root: str,
        input_nullifiers: list[str],
        output_commitments: list[str],
        proof_hex: str,
        relayer_fee: int,
        public_amount: int = 0,
        payload: dict[str, Any] | None = None,
        expires_at: str | None = None,
        output_payloads: list[str] | None = None,
        client_request_id: str | None = None,
        relayer_id: str | None = None,
    ) -> ShieldedRelayerJobResult:
        return run_sync(
            self._async_client.submit_shielded_command(
                contract=contract,
                target_contract=target_contract,
                old_root=old_root,
                input_nullifiers=input_nullifiers,
                output_commitments=output_commitments,
                proof_hex=proof_hex,
                relayer_fee=relayer_fee,
                public_amount=public_amount,
                payload=payload,
                expires_at=expires_at,
                output_payloads=output_payloads,
                client_request_id=client_request_id,
                relayer_id=relayer_id,
            )
        )

    def get_job(
        self, job_id: str, *, relayer_id: str | None = None
    ) -> ShieldedRelayerJobResult:
        return run_sync(
            self._async_client.get_job(job_id, relayer_id=relayer_id)
        )
