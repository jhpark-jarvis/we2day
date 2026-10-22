from datetime import date as Date
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from we2day_api.auth import CurrentUser, require_user
from we2day_api.calendar import Store

router = APIRouter(tags=["questions"])
User = Annotated[CurrentUser, Depends(require_user)]


class NewQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: Date = Field(ge=Date(2000, 1, 1), le=Date(2100, 12, 31))
    prompt: str = Field(min_length=1, max_length=500)
    request_id: UUID


class Question(BaseModel):
    id: UUID
    date: Date
    prompt: str
    created_by: UUID
    created_at: datetime


class AnswerChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    content: str = Field(max_length=2000)
    shared: bool
    skipped: bool
    expected_version: int = Field(ge=0, le=2_147_483_646)
    request_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")

    @model_validator(mode="after")
    def shareable(self):
        if self.shared and (self.skipped or not self.content.strip()):
            raise ValueError("A shared answer must contain text and cannot be skipped")
        return self


class Answer(BaseModel):
    question_id: UUID
    author_id: UUID
    content: str
    shared: bool
    skipped: bool
    version: int
    updated_at: datetime


class QuestionView(BaseModel):
    question: Question
    mine: Answer | None
    partner: Answer | None


Q_FIELDS = "id,date,prompt,created_by,created_at"
A_FIELDS = "question_id,author_id,content,shared,skipped,version,updated_at"


@router.get("/questions", response_model=list[Question])
def list_questions(
    store: Store,
    date: Annotated[Date, Query(ge=Date(2000, 1, 1), le=Date(2100, 12, 31))],
    offset: int = Query(0, ge=0, le=100000),
):
    return store.call(
        "GET",
        "couple_questions",
        params={
            "select": Q_FIELDS,
            "date": f"eq.{date}",
            "order": "id.asc",
            "limit": "50",
            "offset": str(offset),
        },
    )


@router.post("/questions/{id}", response_model=Question)
def create_question(id: UUID, body: NewQuestion, store: Store):
    if not body.prompt.strip():
        raise HTTPException(422, "invalid_question")
    return store.rpc(
        "create_question",
        {
            "p_id": str(id),
            **{f"p_{k}": v for k, v in body.model_dump(mode="json").items()},
        },
    )[0]


@router.get("/questions/{id}", response_model=QuestionView)
def read_question(id: UUID, store: Store, user: User):
    rows = store.call(
        "GET",
        "couple_questions",
        params={
            "select": Q_FIELDS,
            "id": f"eq.{id}",
            "limit": "1",
        },
    )
    if not rows:
        raise HTTPException(404, "question_not_found")
    answers = store.call(
        "GET",
        "question_answers",
        params={
            "select": A_FIELDS,
            "question_id": f"eq.{id}",
            "order": "author_id.asc",
            "limit": "2",
        },
    )
    return {
        "question": rows[0],
        "mine": next((a for a in answers if a["author_id"] == str(user.id)), None),
        "partner": next(
            (
                a
                for a in answers
                if a["author_id"] != str(user.id) and a["shared"] and not a["skipped"]
            ),
            None,
        ),
    }


@router.post("/questions/{id}/answer", response_model=Answer)
def save_answer(id: UUID, body: AnswerChange, store: Store):
    return store.rpc(
        "save_question_answer",
        {
            "p_question_id": str(id),
            **{f"p_{k}": v for k, v in body.model_dump(mode="json").items()},
        },
    )[0]
