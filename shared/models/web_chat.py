"""Owner-visible web chat records; separate from core's reasoning context."""
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from shared.models.websearch import TurnWebSearch


class ChatCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=120)


class ChatRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    title: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatTurn(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    text: str
    reply: str | None = None
    status: Literal['pending', 'complete', 'unknown'] = 'pending'
    web_search: TurnWebSearch | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatDetail(ChatRecord):
    turns: list[ChatTurn] = Field(default_factory=list)
