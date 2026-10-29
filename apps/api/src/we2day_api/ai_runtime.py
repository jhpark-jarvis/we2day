"""Request-local numeric telemetry and cancellable, bounded I/O. No content logging."""

import asyncio
import json
import logging
import time
from contextlib import contextmanager

import httpx
from fastapi import HTTPException

from we2day_api.data import DataAPI, data_response
from we2day_api.timing import current_timings
from we2day_api.upstream import BorrowedAsyncTransport


class RunStats:
    def __init__(self, version, progress=None):
        self.started = time.monotonic()
        self.version = version
        self.durations = {}
        self.counts = {"model_calls": 0, "request_bytes": 0, "response_bytes": 0}
        self.error_category = None
        self.progress = progress

    def stage(self, label):
        if self.progress:
            self.progress(label)

    @contextmanager
    def span(self, label):
        if label not in {"context", "model", "tools", "persist"}:
            raise ValueError("Invalid metric category")
        self.stage(label)
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - start
            self.durations[label] = self.durations.get(label, 0) + elapsed * 1000
            timing = current_timings.get()
            if timing:
                timing.add("ai_" + label, elapsed)

    def usage(self, payload):
        usage = payload.get("usage", {})
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key) if isinstance(usage, dict) else None
            if type(value) is int and 0 <= value <= 2_147_483_647:
                self.counts[key] = self.counts.get(key, 0) + value
        details = usage.get("prompt_tokens_details", {}) if isinstance(usage, dict) else {}
        cached = details.get("cached_tokens") if isinstance(details, dict) else None
        if type(cached) is int and 0 <= cached <= 2_147_483_647:
            self.counts["cached_tokens"] = self.counts.get("cached_tokens", 0) + cached

    def emit(self, status):
        # Fixed keys/categories only. Never include exception text, IDs, URLs or arguments.
        value = {
            "version": self.version,
            "status": status,
            "ms": {k: round(v, 1) for k, v in self.durations.items()},
            "total_ms": round((time.monotonic() - self.started) * 1000, 1),
            **self.counts,
        }
        if self.error_category:
            value["error_category"] = self.error_category
        logging.getLogger("uvicorn.error").info("ai_run %s", json.dumps(value))

    def error(self, detail):
        from we2day_api.ai_metrics import CATEGORIES

        if isinstance(detail, str) and detail in CATEGORIES:
            self.error_category = detail


class Budget:
    def __init__(self, seconds=85):
        self.deadline = time.monotonic() + seconds

    def remaining(self, limit=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("AI deadline")
        return min(remaining, limit) if limit is not None else remaining


async def bounded_response(client, method, url, budget, *, limit, seconds, **kwargs):
    """Whole-operation timeout, including slow-drip response bodies and pool wait."""
    async with asyncio.timeout(budget.remaining(seconds)):
        async with client.stream(
            method, url, timeout=budget.remaining(seconds), **kwargs
        ) as response:
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                budget.remaining()
                raw.extend(chunk)
                if len(raw) > limit:
                    raise HTTPException(502, "ai_invalid_response")
            return response.status_code, bytes(raw)


class AIStore:
    """Borrow caller credentials only for fixed Supabase requests, never for provider I/O."""

    def __init__(self, store, client, budget, stats):
        self.store, self.client, self.budget, self.stats = store, client, budget, stats

    async def call(self, method, path, **kwargs):
        if not isinstance(self.store, DataAPI):
            # In-memory test doubles only; production always uses the async network path.
            return self.store.call(method, path, **kwargs)
        transport = self.store.transport
        # The fixed author-scoped history RPC returns at most fifty bounded turns.
        # Only legacy alias repair uses it; provider and ordinary DB limits stay small.
        history_read = (
            method == "POST"
            and path == "rpc/read_ai_conversations"
            and isinstance(kwargs.get("json"), dict)
            and bool(kwargs["json"].get("p_id"))
        )
        status, raw = await bounded_response(
            self.client,
            method,
            str(transport.base_url.join(path)),
            self.budget,
            limit=3_145_728 if history_read else 131072,
            seconds=8,
            headers=dict(transport.headers),
            **kwargs,
        )
        self.stats.counts["data_response_bytes"] = self.stats.counts.get(
            "data_response_bytes", 0
        ) + len(raw)
        return data_response(httpx.Response(status, content=raw))

    async def rpc(self, name, body=None):
        if not isinstance(self.store, DataAPI):
            return self.store.rpc(name, body) if body is not None else self.store.rpc(name)
        return await self.call("POST", "rpc/" + name, json=body or {})


async def with_disconnect(operation, request, budget):
    async def watch():
        while not asyncio.current_task().cancelling():
            if await request.is_disconnected():
                return
            await asyncio.sleep(0.2)

    work = asyncio.create_task(operation)
    disconnected = asyncio.create_task(watch())
    try:
        async with asyncio.timeout(budget.remaining()):
            done, _ = await asyncio.wait((work, disconnected), return_when=asyncio.FIRST_COMPLETED)
            if work in done:
                return await work
            raise HTTPException(499, "ai_request_cancelled")
    finally:
        work.cancel()
        disconnected.cancel()
        await asyncio.gather(work, disconnected, return_exceptions=True)


def ai_transport(request):
    return BorrowedAsyncTransport(request.app.state.ai_pool)
