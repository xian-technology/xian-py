import asyncio

import aiohttp

from xian_py import XianAsync


def test_reused_client_closes_new_session_but_preserves_external_session():
    async def scenario():
        async with aiohttp.ClientSession() as external:
            client = XianAsync("http://127.0.0.1:26657", session=external)
            async with client:
                assert client.session is external
            assert not external.closed

            async with client:
                owned = client.session
                assert owned is not external
                assert not owned.closed
            try:
                assert owned.closed
                assert not external.closed
            finally:
                await owned.close()
                await client.close()

    asyncio.run(scenario())
