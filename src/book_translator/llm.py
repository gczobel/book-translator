"""Our own LLM interface (ADR 0003): a request and an output schema in, a validated result out."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ValidationError

from book_translator.budget import Budget
from book_translator.cache import CallCache
from book_translator.config import FALLBACK_MODELS, PRICES


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


REASONING_REFUSAL = "reasoning_extraction"
BILLED_REFUSALS = {"bio", "frontier_llm", REASONING_REFUSAL}  # the provider charges for these


class ModelRefusedError(Exception):
    """The provider refused the request (a content filter), so there is no answer to read."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "",
        key: str = "",
        attempts: int = 0,
        log: Path | None = None,
        category: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        super().__init__(message)
        self.category = category  # the provider's reason class, e.g. "reasoning_extraction"
        self.input_tokens = input_tokens  # what the refused call cost, if the provider billed it
        self.output_tokens = output_tokens
        self.stage = stage
        self.key = key
        self.attempts = attempts
        self.detail = message  # the provider's own words
        self.log = log  # the file holding them, if it could be written


MAX_LOGGED_CHARS = 20_000
_SECRET = re.compile(r"\b(?:sk|pk|key|tok)-[A-Za-z0-9_-]{8,}")


def _redact(text: str) -> str:
    return _SECRET.sub("[redacted]", text)


def _write_log(database: Path, name: str, record: dict[str, object]) -> Path | None:
    path = database.parent / "logs" / name
    try:
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return None
    return path


def save_invalid(
    database: Path, stage: str, key: str, raw: str, error: str, attempts: int
) -> Path | None:
    """Keep the last invalid answer next to the database, bounded; None if it cannot be written."""
    record = {
        "stage": stage,
        "key": key,
        "attempts": attempts,
        "error": _redact(error)[:MAX_LOGGED_CHARS],
        "raw": _redact(raw)[:MAX_LOGGED_CHARS],
        "raw_truncated": len(raw) > MAX_LOGGED_CHARS,
    }
    return _write_log(database, f"invalid-{key}.json", record)


def save_refused(database: Path, stage: str, key: str, message: str, attempts: int) -> Path | None:
    """Keep the provider's refusal next to the database; None if it cannot be written."""
    record = {
        "stage": stage,
        "key": key,
        "attempts": attempts,
        "refusal": _redact(message)[:MAX_LOGGED_CHARS],
    }
    return _write_log(database, f"refused-{key}.json", record)


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
    reworded: bool = False  # set after a reasoning refusal: the adapter asks for plainer answers


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


def _describe(asked: LLMRequest, exc: ModelRefusedError) -> str:
    how = "reworded" if asked.reworded else "as asked"
    why = f", {exc.category}" if exc.category else ""
    return f"{asked.model.split(':', 1)[-1]} {how}{why}"


class LLM:
    def _record_refusal(self, stage: str, model: str, exc: ModelRefusedError) -> None:
        """A refused call the provider bills counts against the spending cap."""
        if self._budget is not None and exc.category in BILLED_REFUSALS:
            self._budget.record(stage, cost_of(model, exc.input_tokens, exc.output_tokens))

    def __init__(
        self,
        adapter: Adapter,
        database: Path,
        max_attempts: int = 3,
        budget: Budget | None = None,
        fallbacks: Mapping[str, str] | None = None,
    ) -> None:
        self._fallbacks = FALLBACK_MODELS if fallbacks is None else fallbacks
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
        refused: ModelRefusedError | None = None
        last = ""
        asked = replace(request, output_schema=json.dumps(schema.model_json_schema()))
        trail: list[str] = []
        switched = False
        for attempt in range(self._max_attempts):
            if error is not None:
                asked = replace(asked, feedback=str(error))
            if self._budget is not None:
                self._budget.check(_projected_cost(asked))
            try:
                raw = self._adapter.complete(asked, key, attempt)
            except ModelRefusedError as exc:
                refused = exc
                trail.append(_describe(asked, exc))
                self._record_refusal(request.stage, asked.model, exc)
                if switched:
                    break  # the fallback model refused too
                if exc.category == REASONING_REFUSAL and not asked.reworded:
                    asked = replace(asked, reworded=True)  # the same ask, in plainer words
                elif (other := self._fallbacks.get(asked.model)) is not None:
                    asked, switched = replace(asked, model=other), True
                else:
                    break  # nothing left to change; sending it again would be refused again
                continue
            refused = None
            if self._budget is not None:
                self._budget.record(
                    request.stage, cost_of(asked.model, raw.input_tokens, raw.output_tokens)
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
            cost = cost_of(asked.model, input_tokens, output_tokens)
            return Result(output, Usage(input_tokens, output_tokens, cost))
        if refused is not None:
            message = f"{refused} [tried: {'; '.join(trail)}]"
            log = save_refused(self._database, request.stage, key, message, len(trail))
            raise ModelRefusedError(
                message,
                stage=request.stage,
                key=key,
                attempts=len(trail),
                log=log,
                category=refused.category,
            )
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
