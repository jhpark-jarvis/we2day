"""Transient NAVER API HUB search shared by authenticated UI and bounded AI tools."""

import math
import re
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
    # Provider evidence is request-local and never part of the UI/model wire contract.
    mapx: str = Field(default="", exclude=True, repr=False)
    mapy: str = Field(default="", exclude=True, repr=False)

    @field_validator("mapx", "mapy", mode="before")
    @classmethod
    def optional_coordinate(cls, value):
        if type(value) not in (str, int, float):
            return ""
        text = str(value).strip()
        return text if len(text) <= 24 and re.fullmatch(r"\d+(?:\.\d+)?", text) else ""

    @property
    def coordinates(self) -> tuple[float, float] | None:
        if not self.mapx or not self.mapy:
            return None
        x, y = float(self.mapx), float(self.mapy)
        # Both axes must have the same representation. Old projected coordinates,
        # swapped axes and invalid optional fields must not poison usable search rows.
        if x > 180 and y > 90 and "." not in self.mapx and "." not in self.mapy:
            x, y = x / 10_000_000, y / 10_000_000
        return (x, y) if 124 <= x <= 133 and 32 <= y <= 40 else None


def straight_line_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Only for ordering observed Korean place coordinates, never travel time."""
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    value = math.sin((lat2 - lat1) / 2) ** 2 + (
        math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6_371_008.8 * 2 * math.asin(math.sqrt(min(1, max(0, value))))


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
    return fetch_places(request.app.state.settings, body.query)


def place_request(config, query: str) -> dict:
    """One wire contract for sync UI and async AI; never caller credentials."""
    query = SearchInput(query=query).query
    if not (
        config.naver_search_enabled
        and config.naver_search_client_id
        and config.naver_search_client_secret
    ):
        raise HTTPException(503, "place_search_not_configured")
    return {
        "url": HUB_URL,
        "params": {"query": query, "display": 5, "start": 1, "sort": "random"},
        "headers": {
            "X-NCP-APIGW-API-KEY-ID": config.naver_search_client_id,
            "X-NCP-APIGW-API-KEY": config.naver_search_client_secret,
        },
    }


def parse_place_response(status: int, raw: bytes) -> SearchResults:
    if status == 429:
        raise HTTPException(429, "place_search_limited")
    if status != 200 or len(raw) > 65536:
        raise HTTPException(503, "place_search_unavailable")
    try:
        return SearchResults.model_validate_json(raw)
    except ValidationError as error:
        raise HTTPException(503, "place_search_unavailable") from error


def fetch_places(config, query: str) -> SearchResults:
    """Fixed provider request; callers enforce authentication and their own tool budget."""
    spec = place_request(config, query)
    try:
        # Fixed destination, no caller JWT, redirects, cookies, response cache or retries.
        with httpx.Client(timeout=4.0, follow_redirects=False, trust_env=False) as client:
            with client.stream(
                "GET",
                **spec,
            ) as result:
                if result.status_code != 200:
                    return parse_place_response(result.status_code, b"")
                data = bytearray()
                for chunk in result.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 65_536:
                        raise HTTPException(503, "place_search_unavailable")
                return parse_place_response(result.status_code, data)
    except httpx.HTTPError as error:
        # Never expose provider responses, secrets, search queries or exception URLs.
        raise HTTPException(503, "place_search_unavailable") from error
