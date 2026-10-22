"""Transient, authenticated NAVER API HUB search. No persistence or AI reuse."""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from we2day_api.data import DataAPI, require_data

router = APIRouter(tags=["places"])
Store = Annotated[DataAPI, Depends(require_data)]
HUB_URL = "https://naverapihub.apigw.ntruss.com/search/v1/local"


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=100)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Invalid query")
        return value.strip()


class PlaceResult(BaseModel):
    model_config = ConfigDict(strict=True)
    title: str = Field(max_length=2000)
    link: str = Field(default="", max_length=4000)
    category: str = Field(default="", max_length=2000)
    description: str = Field(default="", max_length=4000)
    address: str = Field(default="", max_length=2000)
    roadAddress: str = Field(default="", max_length=2000)


class SearchResults(BaseModel):
    items: list[PlaceResult] = Field(max_length=5)


async def read_search(request: Request) -> SearchInput:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "invalid_place_search")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 2048:
            raise HTTPException(413, "invalid_place_search")
        body.extend(chunk)
    try:
        return SearchInput.model_validate_json(body)
    except ValidationError as error:
        raise HTTPException(422, "invalid_place_search") from error


@router.post("/places/search", response_model=SearchResults)
def search_places(
    request: Request,
    store: Store,
    body: Annotated[SearchInput, Depends(read_search)],
):
    if not store.rpc("get_my_couple"):
        raise HTTPException(403, "couple_required")
    config = request.app.state.settings
    if not (
        config.naver_search_enabled
        and config.naver_search_client_id
        and config.naver_search_client_secret
    ):
        raise HTTPException(503, "place_search_not_configured")
    try:
        # Fixed destination, no caller JWT, redirects, cookies, response cache or retries.
        with httpx.Client(timeout=4.0, follow_redirects=False) as client:
            with client.stream(
                "GET",
                HUB_URL,
                params={"query": body.query, "display": 5, "start": 1, "sort": "random"},
                headers={
                    "X-NCP-APIGW-API-KEY-ID": config.naver_search_client_id,
                    "X-NCP-APIGW-API-KEY": config.naver_search_client_secret,
                },
            ) as result:
                if result.status_code == 429:
                    raise HTTPException(429, "place_search_limited")
                if not result.is_success:
                    raise HTTPException(503, "place_search_unavailable")
                data = bytearray()
                for chunk in result.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 65_536:
                        raise HTTPException(503, "place_search_unavailable")
                return SearchResults.model_validate_json(data)
    except (httpx.HTTPError, ValidationError) as error:
        # Never expose provider responses, secrets, search queries or exception URLs.
        raise HTTPException(503, "place_search_unavailable") from error
