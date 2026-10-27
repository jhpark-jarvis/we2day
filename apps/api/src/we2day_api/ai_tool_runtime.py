"""Parallelize independent reads, commit their evidence in stable model-call order."""

import asyncio
import json

from fastapi import HTTPException

from we2day_api.ai_place_policy import SearchArguments
from we2day_api.ai_runtime import bounded_response
from we2day_api.ai_tools import weather_requests
from we2day_api.places import HUB_URL, SearchInput, SearchResults


class ToolIO:
    def __init__(self, settings, client, store, budget, stats):
        self.settings, self.client, self.store = settings, client, store
        self.budget, self.stats = budget, stats
        self.slots = asyncio.Semaphore(2)

    async def perform(self, action):
        search = action[0] == "places"
        if search:
            self.stats.counts["search_calls"] = self.stats.counts.get("search_calls", 0) + 1
        try:
            result = await self._perform(action)
        except TimeoutError as error:
            if search:
                self.stats.counts["search_errors"] = self.stats.counts.get("search_errors", 0) + 1
            self.budget.remaining()  # Overall expiry propagates, per-tool expiry is a failed read.
            raise HTTPException(503, "tool_unavailable") from error
        except Exception:
            if search:
                self.stats.counts["search_errors"] = self.stats.counts.get("search_errors", 0) + 1
            raise
        else:
            if search:
                for key, value in {
                    "search_successes": 1,
                    "search_empty": int(not result.items),
                    "search_candidates": len(result.items),
                }.items():
                    self.stats.counts[key] = self.stats.counts.get(key, 0) + value
            return result

    async def _perform(self, action):
        async with self.slots:
            self.budget.remaining()
            kind = action[0]
            if kind == "data":
                return await self.store.call("GET", action[1], params=action[2])
            if kind == "places":
                query = SearchInput(query=action[1]).query
                config = self.settings
                if not (
                    config.naver_search_enabled
                    and config.naver_search_client_id
                    and config.naver_search_client_secret
                ):
                    raise HTTPException(503, "place_search_not_configured")
                status, raw = await bounded_response(
                    self.client,
                    "GET",
                    HUB_URL,
                    self.budget,
                    limit=65536,
                    seconds=4,
                    params={"query": query, "display": 5, "start": 1, "sort": "random"},
                    headers={
                        "X-NCP-APIGW-API-KEY-ID": config.naver_search_client_id,
                        "X-NCP-APIGW-API-KEY": config.naver_search_client_secret,
                    },
                )
                if status == 429:
                    raise HTTPException(429, "place_search_limited")
                if status != 200:
                    raise HTTPException(503, "place_search_unavailable")
                return SearchResults.model_validate_json(raw)
            if kind == "weather":
                steps = weather_requests(action[1])
                try:
                    url, params = next(steps)
                    while True:
                        status, raw = await bounded_response(
                            self.client,
                            "GET",
                            url,
                            self.budget,
                            params=params,
                            limit=24000,
                            seconds=4,
                        )
                        if status != 200:
                            raise HTTPException(503, "weather_unavailable")
                        url, params = steps.send(json.loads(raw))
                except StopIteration as done:
                    return done.value
            raise ValueError("Invalid internal I/O operation")


async def execute_batch(session, calls, io):
    """Reserve budgets before I/O. Never race candidate refs or duplicate queries."""
    # Repeated calls in one wave use the completed request-local cache sequentially.
    keys = []
    for call in calls:
        name, arguments = call["function"]["name"], call["function"]["arguments"]
        try:
            if len(arguments.encode()) <= 12000:
                value = json.loads(arguments)
                if name == "search_places":
                    value = SearchArguments.model_validate(value).model_dump()
                arguments = json.dumps(value, sort_keys=True, ensure_ascii=False)
        except (ValueError, TypeError):
            pass
        keys.append((name, arguments))
    if len(set(keys)) != len(keys):
        results = []
        for call in calls:
            results.extend(await execute_batch(session, [call], io))
        return results
    generators = [session._execute_steps(*key) for key in keys]
    actions, results = {}, [None] * len(calls)
    for index, steps in enumerate(generators):
        try:
            actions[index] = next(steps)
        except StopIteration as done:
            results[index] = done.value
    while actions:
        indices = list(actions)
        outcomes = await asyncio.gather(
            *(io.perform(actions[index]) for index in indices),
            return_exceptions=True,
        )
        actions = {}
        for index, outcome in zip(indices, outcomes, strict=True):
            try:
                if isinstance(outcome, BaseException):
                    if not isinstance(outcome, Exception):
                        raise outcome
                    actions[index] = generators[index].throw(outcome)
                else:
                    actions[index] = generators[index].send(outcome)
            except StopIteration as done:
                results[index] = done.value
    return results
