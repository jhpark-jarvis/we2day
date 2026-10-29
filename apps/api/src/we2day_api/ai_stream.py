"""Finite request-local SSE feedback. No unvalidated tokens, durable jobs or content logs."""

import asyncio
import json

from fastapi import HTTPException

STAGES = frozenset({"accepted", "context", "model", "search", "tools", "validate", "persist"})


def frame(event, data):
    return (
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


async def events(run, *, heartbeat=5):
    queue = asyncio.Queue(maxsize=32)
    previous = None

    def progress(stage):
        nonlocal previous
        if stage not in STAGES:
            raise ValueError("Unknown public progress stage")
        if stage == previous:
            return
        previous = stage
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(stage)

    async def work():
        try:
            result = await run(progress)
            return "result", result.model_dump(mode="json")
        except HTTPException as error:
            # Only stable application codes, never exception text/provider responses.
            from we2day_api.ai_metrics import CATEGORIES

            codes = CATEGORIES | {
                "ai_request_in_progress",
                "ai_lease_expired",
                "ai_request_cancelled",
                "ai_daily_limit",
                "ai_conversation_not_found",
                "request_conflict",
            }
            code = (
                error.detail
                if isinstance(error.detail, str) and error.detail in codes
                else "ai_unavailable"
            )
            return "error", {"code": code, "status": error.status_code}
        except TimeoutError:
            return "error", {"code": "ai_timeout", "status": 503}
        except Exception:
            return "error", {"code": "ai_unavailable", "status": 503}

    task = asyncio.create_task(work())
    waiting = None
    try:
        yield frame("progress", {"stage": "accepted"})
        while True:
            waiting = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait(
                (task, waiting), timeout=heartbeat, return_when=asyncio.FIRST_COMPLETED
            )
            if waiting in done:
                yield frame("progress", {"stage": waiting.result()})
            else:
                waiting.cancel()
                await asyncio.gather(waiting, return_exceptions=True)
            if task in done:
                while not queue.empty():
                    yield frame("progress", {"stage": queue.get_nowait()})
                event, data = await task
                yield frame(event, data)
                break
            if not done:
                yield ": heartbeat\n\n"
    finally:
        task.cancel()
        if waiting:
            waiting.cancel()
        await asyncio.gather(task, *([waiting] if waiting else []), return_exceptions=True)
