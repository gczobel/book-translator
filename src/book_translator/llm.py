"""Our own LLM interface (ADR 0003): a request and an output schema in, a validated result out."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class LLMRequest:
    """Everything that determines an answer; it is also what the call cache is keyed by."""

    stage: str
    prompt_version: str
    model: str
    prompt: str
    bible_slice: str
    source_text: str


@dataclass(frozen=True)
class RawAnswer:
    """What an adapter returns: the model's text and the tokens it cost."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class Adapter(Protocol):
    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer: ...


@dataclass(frozen=True)
class Result[T: BaseModel]:
    output: T


def request_key(request: LLMRequest) -> str:
    """Hash of stage, prompt version, model, bible slice and source text."""
    parts = [
        request.stage,
        request.prompt_version,
        request.model,
        request.prompt,
        request.bible_slice,
        request.source_text,
    ]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


class LLM:
    def __init__(self, adapter: Adapter, database: Path) -> None:
        self._adapter = adapter
        self._database = database

    def call[T: BaseModel](self, request: LLMRequest, schema: type[T]) -> Result[T]:
        key = request_key(request)
        raw = self._adapter.complete(request, key, 0)
        return Result(schema.model_validate_json(raw.text))
