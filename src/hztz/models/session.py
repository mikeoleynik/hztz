"""Файл сессии `.hz/chat/ses_*.json`. Граф здесь не хранится."""

from typing import Annotated, Literal

from pydantic import Field

from hztz.models.state import HZModel


class ThinkingPart(HZModel):
    type: Literal["thinking"] = "thinking"
    text: str


class TextPart(HZModel):
    type: Literal["text"] = "text"
    text: str


class PatchPart(HZModel):
    type: Literal["patch"] = "patch"
    path: str
    added: int
    removed: int
    hunk: str


Part = Annotated[ThinkingPart | TextPart | PatchPart, Field(discriminator="type")]


class UserMessage(HZModel):
    role: Literal["user"] = "user"
    text: str


class AssistantMessage(HZModel):
    role: Literal["assistant"] = "assistant"
    parts: list[Part] = Field(default_factory=list)


class HzMessage(HZModel):
    role: Literal["hz"] = "hz"
    text: str


Message = Annotated[UserMessage | AssistantMessage | HzMessage, Field(discriminator="role")]


class ChatSession(HZModel):
    id: str
    title: str = ""
    persona: str
    spec_hash: str = ""
    log_cursor: int = 0
    messages: list[Message] = Field(default_factory=list)
