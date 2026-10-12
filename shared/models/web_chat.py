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


class ChatDocumentRef(BaseModel):
    """The document a saved chat is answering from (Phase 50). The id is the Reachy document id; the title is kept so the chat reads the same later. `available` is filled in when the chat is
    read (the document may have been deleted since) and is never stored."""

    id: str = Field(min_length=1, max_length=64)
    title: str = Field(max_length=200)
    available: bool = True


class ChatCitation(BaseModel):
    """A page whose excerpts were supplied for a reply; never a page number the model wrote."""

    document_id: str
    title: str
    page: int


class ChatDocumentSet(BaseModel):
    user_id: str = Field(min_length=1, max_length=256)
    document_id: str | None = Field(default=None, max_length=64)  # None removes the attachment


class ChatTurn(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    text: str
    reply: str | None = None
    status: Literal['pending', 'complete', 'unknown'] = 'pending'
    web_search: TurnWebSearch | None = None
    document: ChatDocumentRef | None = None  # the attachment this reply was answered under
    citations: list[ChatCitation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatDetail(ChatRecord):
    turns: list[ChatTurn] = Field(default_factory=list)
    document: ChatDocumentRef | None = None  # the current attachment of this conversation, if any
