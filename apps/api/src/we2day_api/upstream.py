"""Reuse sockets only; each caller still owns its client, headers, cookies and SDK."""

import httpx
from fastapi import Request


class BorrowedTransport(httpx.BaseTransport):
    def __init__(self, pool: httpx.BaseTransport):
        self.pool = pool

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self.pool.handle_request(request)

    def close(self) -> None:
        # FastAPI lifespan owns the pool. Closing a caller's client must not close it.
        pass


def upstream_transport(request: Request) -> httpx.BaseTransport:
    return BorrowedTransport(request.app.state.upstream_pool)


class BorrowedAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, pool: httpx.AsyncBaseTransport):
        self.pool = pool

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.pool.handle_async_request(request)

    async def aclose(self):
        # Lifespan alone owns socket pool shutdown. Clients never share headers/cookies.
        pass
