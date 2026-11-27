"""Our own LLM interface (ADR 0003): a request and an output schema in, a validated result out."""

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ValidationError

from book_translator.budget import Budget
from book_translator.cache import CallCache
from book_translator.config import PRICES


class InvalidOutputError(Exception):
    """The model kept returning output that does not match the schema."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "",
        key: str = "",
        attempts: int = 0,
        detail: str = "",
        log: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.key = key
        self.attempts = attempts
        self.detail = detail  # the validation error
        self.log = log  # the file holding the raw answer, if it could be written


MAX_LOGGED_CHARS = 20_000
_SECRET = re.compile(r"\b(?:sk|pk|key|tok)-[A-Za-z0-9_-]{8,}")


def _redact(text: str) -> str:
    return _SECRET.sub("[redacted]", text)


def save_invalid(
    database: Path, stage: str, key: str, raw: str, error: str, attempts: int
) -> Path | None:
    """Keep the last invalid answer next to the database, bounded; None if it cannot be written."""
    path = database.parent / "logs" / f"invalid-{key}.json"
    record = {
        "stage": stage,
        "key": key,
        "attempts": attempts,
        "error": _redact(error)[:MAX_LOGGED_CHARS],
        "raw": _redact(raw)[:MAX_LOGGED_CHARS],
        "raw_truncated": len(raw) > MAX_LOGGED_CHARS,
    }
    try:
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return None
    return path


@dataclass(frozen=True)
class LLMRequest:
    """Everything that determines an answer; it is also what the call cache is keyed by."""

    stage: str
    prompt_version: str
    model: str
    prompt: str
    bible_slice: str
    source_text: str
    # Filled in by `LLM.call` for the adapter; not part of `request_key`, so recordings stay valid.
    output_schema: str = ""
    feedback: str = ""


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


_FENCE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n(.*?)\n?```\s*$", re.DOTALL)


def strip_fences(text: str) -> str:
    """Models often wrap JSON in a markdown code fence; take what is inside it."""
    match = _FENCE.match(text.strip())
    return match.group(1) if match else text


def _projected_cost(request: LLMRequest) -> float:
    """A rough guess before the call: about 4 characters per token, and as many tokens back."""
    tokens = (len(request.prompt) + len(request.bible_slice) + len(request.source_text)) // 4
    return cost_of(request.model, tokens, tokens)


class LLM:
    def __init__(
        self,
        adapter: Adapter,
        database: Path,
        max_attempts: int = 3,
        budget: Budget | None = None,
    ) -> None:
        self._adapter = adapter
        self._budget = budget
        self._cache = CallCache(database)
        self._database = database
        self._max_attempts = max_attempts

    def call[T: BaseModel](self, request: LLMRequest, schema: type[T]) -> Result[T]:
        key = request_key(request)
        cached = self._cache.get(key)
        if cached is not None:
            return Result(schema.model_validate_json(cached), NO_USAGE)
        input_tokens = output_tokens = 0
        error: ValidationError | None = None
        last = ""
        asked = replace(request, output_schema=json.dumps(schema.model_json_schema()))
        for attempt in range(self._max_attempts):
            if error is not None:
                asked = replace(asked, feedback=str(error))
            if self._budget is not None:
                self._budget.check(_projected_cost(request))
            raw = self._adapter.complete(asked, key, attempt)
            if self._budget is not None:
                self._budget.record(
                    request.stage, cost_of(request.model, raw.input_tokens, raw.output_tokens)
                )
            last = raw.text
            input_tokens += raw.input_tokens
            output_tokens += raw.output_tokens
            try:
                output = schema.model_validate_json(strip_fences(raw.text))
            except ValidationError as exc:
                error = exc
                continue
            self._cache.put(key, strip_fences(raw.text))
            cost = cost_of(request.model, input_tokens, output_tokens)
            return Result(output, Usage(input_tokens, output_tokens, cost))
        log = save_invalid(self._database, request.stage, key, last, str(error), self._max_attempts)
        raise InvalidOutputError(
            f"output for key {key} failed validation after {self._max_attempts} attempt(s):"
            f" {error}",
            stage=request.stage,
            key=key,
            attempts=self._max_attempts,
            detail=str(error),
            log=log,
        )
