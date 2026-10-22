"""Compatibility tombstone: place search now opens NAVER Maps directly."""

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["places"])


@router.post("/places/search", deprecated=True)
def retired_place_search():
    # No request body, credentials, provider response or outbound HTTP request.
    raise HTTPException(410, "place_search_moved_to_naver_maps")
