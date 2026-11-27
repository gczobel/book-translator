"""Our own LLM interface (ADR 0003): a request and an output schema in, a validated result out."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ValidationError

from book_translator.cache import CallCache
from book_translator.config import PRICES


class InvalidOutputError(Exception):
    """The model kept returning output that does not match the schema."""


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
class Usage:
    input_tokens: int
    output_tokens: int
    cost_usd: float


NO_USAGE = Usage(0, 0, 0.0)


@dataclass(frozen=True)
class Result[T: BaseModel]:
    output: T
    usage: Usage


def cost_of(model: str, input_tokens: int, output_tokens: int) -> float:
    price = PRICES.get(model)
    if price is None:
        raise ValueError(f"no price known for model {model!r}")
    return (input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok) / 1e6


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
    def __init__(self, adapter: Adapter, database: Path, max_attempts: int = 3) -> None:
        self._adapter = adapter
        self._cache = CallCache(database)
        self._max_attempts = max_attempts

    def call[T: BaseModel](self, request: LLMRequest, schema: type[T]) -> Result[T]:
        key = request_key(request)
        cached = self._cache.get(key)
        if cached is not None:
            return Result(schema.model_validate_json(cached), NO_USAGE)
        input_tokens = output_tokens = 0
        error: ValidationError | None = None
        for attempt in range(self._max_attempts):
            raw = self._adapter.complete(request, key, attempt)
            input_tokens += raw.input_tokens
            output_tokens += raw.output_tokens
            try:
                output = schema.model_validate_json(raw.text)
            except ValidationError as exc:
                error = exc
                continue
            self._cache.put(key, raw.text)
            cost = cost_of(request.model, input_tokens, output_tokens)
            return Result(output, Usage(input_tokens, output_tokens, cost))
        raise InvalidOutputError(
            f"output for key {key} failed validation after {self._max_attempts} attempt(s): {error}"
        )
