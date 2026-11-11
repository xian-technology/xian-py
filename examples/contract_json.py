"""Read contract-facing HTTP numbers from their original JSON digits."""

import json
from decimal import Decimal

from fastapi import Request
from fastapi.routing import APIRoute


def invalid_number(token: str):
    raise json.JSONDecodeError("Contract numbers must be finite", token, 0)


class ContractJsonRequest(Request):
    async def json(self):
        return json.loads(await self.body(), parse_float=Decimal, parse_constant=invalid_number)


class ContractJsonRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request):
            return await handler(ContractJsonRequest(request.scope, request.receive))

        return handle
