"""Explicitly submitted text only; no database context or model-directed writes."""

import json
import re
from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from we2day_api.calendar import Store
from we2day_api.plans import PlanContent

router = APIRouter(tags=["ai-planner"])
PROMPT_VERSION = "we2-ai-2026-10-26-v1"
MODEL = "@cf/qwen/qwen3-30b-a3b-fp8"
SYSTEM = """당신은 WE2DAY의 '위투 AI'입니다. 한국어로 데이트 대화와 코스 제안만 수행합니다.
DB 조회·저장·확정·검색을 실행하지 않으며 실행했다고 말하지 마세요.
입력에 없는 사실, 실제 주소·영업시간·지도 URL을 만들어내지 마세요.
장소는 사용자가 입력한 이름 또는 '카페 선택' 같은 일반 활동명으로 제안하세요.
개인정보나 비밀번호를 요청하지 마세요. 날짜가 없으면 먼저 물어보세요.
반드시 JSON 객체만 출력하세요: {"reply":"간결한 한국어 답변","plan":null}.
구체적인 날짜의 코스 제안을 요청받으면 plan에 다음 형식의 완전한 객체를 넣으세요:
{"title":"제목","date":"YYYY-MM-DD","budget":null,"transport":"",
"activities":[{"title":"활동","time":"14:00","place":"","cost":null,"note":""}],
"preparation":[]}.
날짜는 2000~2100년, 시간은 HH:mm 또는 null, 금액은 정수 또는 null입니다.
활동은 최대 8개, 준비물은 최대 8개입니다. map_url 필드는 생성하지 마세요.
기존 제안 수정 시 plan 전체를 반환하세요. 저장 여부는 사용자 버튼으로 결정합니다.
/no_think"""


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    # Compatibility only. New UI explicitly submits text without a separate checkbox.
    consent: Literal[True] | None = None
    messages: list[Message] = Field(min_length=1, max_length=12)
    proposal: PlanContent | None = None
    conversation_id: UUID | None = Field(default=None, strict=False)
    request_id: UUID | None = Field(default=None, strict=False)
    version: int = Field(default=0, ge=0)


class ChatResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reply: str = Field(min_length=1, max_length=4000)
    plan: PlanContent | None = None


class SavedChatResult(ChatResult):
    conversation_id: UUID | None = None
    version: int = 0


def complete(settings, messages: list[dict]) -> ChatResult:
    """Fixed host/model, no retries; bounded input/output and no upstream error reflection."""
    if len(json.dumps(messages, ensure_ascii=False).encode()) > 16000:
        raise HTTPException(422, "ai_context_too_long")
    try:
        with httpx.Client(timeout=55, trust_env=False, follow_redirects=False) as client:
            with client.stream(
                "POST",
                f"https://api.cloudflare.com/client/v4/accounts/"
                f"{settings.cloudflare_account_id}/ai/run/{MODEL}",
                headers={"Authorization": f"Bearer {settings.cloudflare_api_token}"},
                json={
                    "messages": messages,
                    "max_tokens": 2048,
                    "temperature": 0.4,
                    "response_format": {"type": "json_object"},
                },
            ) as response:
                if not response.is_success and response.status_code != 429:
                    raise HTTPException(503, "ai_unavailable")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 65536:
                        raise HTTPException(502, "ai_invalid_response")
        if response.status_code == 429:
            try:
                error_payload = json.loads(raw)
                errors = error_payload.get("errors", []) if isinstance(error_payload, dict) else []
                exhausted = any(
                    isinstance(item, dict) and item.get("code") == 3036 for item in errors
                )
            except ValueError:
                exhausted = False
            raise HTTPException(429, "ai_provider_limited" if exhausted else "ai_provider_busy")
        payload = json.loads(raw)
        if payload.get("success") is False:
            raise HTTPException(503, "ai_unavailable")
        result = payload.get("result", {})
        text = result.get("response")
        if text is None:
            text = result["choices"][0]["message"]["content"]
        if isinstance(text, dict):
            answer = ChatResult.model_validate(text)
        else:
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
            answer = ChatResult.model_validate_json(text)
        # The model cannot mint a destination URL. Users select verified places in the editor.
        if answer.plan:
            for activity in answer.plan.activities:
                activity.map_url = ""
        return answer
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError, ValidationError) as error:
        raise HTTPException(502, "ai_invalid_response") from error


@router.get("/ai/planner")
def status(request: Request, response: Response, store: Store):
    response.headers["Cache-Control"] = "private, no-store"
    if not store.rpc("get_my_couple"):
        raise HTTPException(403, "couple_required")
    settings = request.app.state.settings
    return {"available": bool(settings.cloudflare_account_id and settings.cloudflare_api_token)}


@router.get("/ai/planner/history")
def history(
    response: Response, store: Store, conversation_id: UUID | None = None, before: int | None = None
):
    response.headers["Cache-Control"] = "private, no-store"
    return store.rpc(
        "read_ai_conversations",
        {"p_id": str(conversation_id) if conversation_id else None, "p_before": before},
    )


@router.get("/ai/planner/prompt")
def prompt(response: Response, store: Store):
    response.headers["Cache-Control"] = "private, no-store"
    if not store.rpc("get_my_couple"):
        raise HTTPException(403, "couple_required")
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    return {
        "version": PROMPT_VERSION,
        "system": SYSTEM,
        "today": today,
        "model": MODEL,
        "temperature": 0.4,
        "max_tokens": 2048,
        "recent_messages": 11,
        "input_bytes": 16000,
    }


@router.post("/ai/planner", response_model=SavedChatResult)
def chat(body: ChatInput, request: Request, response: Response, store: Store):
    response.headers["Cache-Control"] = "private, no-store"
    settings = request.app.state.settings
    if not settings.cloudflare_account_id or not settings.cloudflare_api_token:
        raise HTTPException(503, "ai_not_configured")
    if body.messages[-1].role != "user":
        raise HTTPException(422, "ai_invalid_messages")
    if bool(body.conversation_id) != bool(body.request_id):
        raise HTTPException(422, "invalid_request")
    if body.conversation_id:
        stored = store.rpc("read_ai_conversations", {"p_id": str(body.conversation_id)})
        if stored:
            for turn in stored["turns"]:
                if turn["request_id"] == str(body.request_id):
                    if turn["user_text"] != body.messages[-1].content:
                        raise HTTPException(409, "request_conflict")
                    return SavedChatResult(
                        **turn["result"],
                        conversation_id=body.conversation_id,
                        version=turn["version"],
                    )
            if stored["version"] != body.version:
                raise HTTPException(409, "version_conflict")
        elif body.version:
            raise HTTPException(404, "ai_conversation_not_found")
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    messages = [{"role": "system", "content": SYSTEM + "\n오늘 한국 날짜: " + today}]
    if body.proposal:
        messages.append(
            {"role": "user", "content": "현재 제안: " + body.proposal.model_dump_json()}
        )
    history = [message.model_dump() for message in body.messages]
    # Keep the latest turns and current proposal, without extra summarization/model calls.
    while (
        len(history) > 1
        and len(json.dumps(messages + history, ensure_ascii=False).encode()) > 16000
    ):
        del history[: min(2, len(history) - 1)]
    messages.extend(history)
    if len(json.dumps(messages, ensure_ascii=False).encode()) > 16000:
        raise HTTPException(422, "ai_context_too_long")
    # Atomic persistent reservation before every billable request, including failed requests.
    if not store.rpc("reserve_ai_planner_request"):
        raise HTTPException(429, "ai_rate_limited")
    answer = complete(settings, messages)
    if body.conversation_id:
        saved = store.rpc(
            "append_ai_conversation",
            {
                "p_id": str(body.conversation_id),
                "p_request": str(body.request_id),
                "p_version": body.version,
                "p_user": body.messages[-1].content,
                "p_result": answer.model_dump(mode="json"),
                "p_prompt": PROMPT_VERSION,
            },
        )
        return SavedChatResult(
            **saved["result"], conversation_id=body.conversation_id, version=saved["version"]
        )
    return SavedChatResult(**answer.model_dump())
