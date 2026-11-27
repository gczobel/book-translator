"""Seam 3: the LLM interface, observed through the replay adapter and the call cache."""

from pathlib import Path

import pytest
from pydantic import BaseModel

from book_translator.llm import (
    LLM,
    InvalidOutputError,
    LLMRequest,
    ModelRefusedError,
    RawAnswer,
    request_key,
)
from book_translator.replay import MissingRecordingError, ReplayAdapter


class Greeting(BaseModel):
    text: str


def make_request(**overrides: str) -> LLMRequest:
    fields = {
        "stage": "draft",
        "prompt_version": "v1",
        "model": "anthropic:claude-sonnet-5-5",
        "prompt": "Say hello.",
        "bible_slice": "bible",
        "source_text": "Hola.",
    }
    fields.update(overrides)
    return LLMRequest(**fields)


def test_a_replayed_call_returns_the_recorded_validated_answer(tmp_path: Path) -> None:
    request = make_request()
    adapter = ReplayAdapter({request_key(request): '{"text": "hello"}'})
    llm = LLM(adapter, tmp_path / "book.sqlite")

    result = llm.call(request, Greeting)

    assert result.output == Greeting(text="hello")


def test_a_missing_recording_fails_naming_the_key(tmp_path: Path) -> None:
    request = make_request()
    llm = LLM(ReplayAdapter({}), tmp_path / "book.sqlite")

    with pytest.raises(MissingRecordingError, match=request_key(request)):
        llm.call(request, Greeting)


def test_a_call_reports_its_tokens_and_cost(tmp_path: Path) -> None:
    request = make_request()
    adapter = ReplayAdapter(
        {request_key(request): '{"text": "hello"}'}, input_tokens=1000, output_tokens=100
    )

    usage = LLM(adapter, tmp_path / "book.sqlite").call(request, Greeting).usage

    assert (usage.input_tokens, usage.output_tokens) == (1000, 100)
    assert usage.cost_usd == pytest.approx(0.0045)  # 1000 * $3/M + 100 * $15/M


def test_a_repeated_call_is_served_from_the_cache_at_zero_cost(tmp_path: Path) -> None:
    request = make_request()
    database = tmp_path / "book.sqlite"
    recorded = ReplayAdapter({request_key(request): '{"text": "hello"}'}, input_tokens=1000)
    LLM(recorded, database).call(request, Greeting)

    # A new interface over the same workspace database, with nothing recorded to replay.
    again = LLM(ReplayAdapter({}), database).call(request, Greeting)

    assert again.output == Greeting(text="hello")
    assert again.usage.cost_usd == 0
    assert again.usage.input_tokens == 0


@pytest.mark.parametrize(
    "change",
    [
        {"model": "anthropic:claude-opus-5-5"},
        {"prompt_version": "v2"},
        {"source_text": "Adiós."},
        {"stage": "polish"},
        {"bible_slice": "other bible"},
    ],
)
def test_changing_an_input_changes_the_key(change: dict[str, str]) -> None:
    assert request_key(make_request(**change)) != request_key(make_request())


def test_the_same_inputs_give_the_same_key() -> None:
    assert request_key(make_request()) == request_key(make_request())


def test_invalid_output_is_retried_and_the_valid_answer_is_returned(tmp_path: Path) -> None:
    request = make_request()
    answers = ['{"wrong": 1}', "not json", '{"text": "hello"}']
    adapter = ReplayAdapter({request_key(request): answers}, input_tokens=10)

    result = LLM(adapter, tmp_path / "book.sqlite").call(request, Greeting)

    assert result.output == Greeting(text="hello")
    assert result.usage.input_tokens == 30  # failed attempts are billed too


def test_invalid_output_gives_up_after_the_attempt_limit(tmp_path: Path) -> None:
    request = make_request()
    adapter = ReplayAdapter({request_key(request): ['{"wrong": 1}', '{"text": "late"}']})
    llm = LLM(adapter, tmp_path / "book.sqlite", max_attempts=1)

    with pytest.raises(InvalidOutputError, match=request_key(request)):
        llm.call(request, Greeting)


def test_invalid_output_is_never_cached(tmp_path: Path) -> None:
    request = make_request()
    database = tmp_path / "book.sqlite"
    bad = ReplayAdapter({request_key(request): '{"wrong": 1}'})
    with pytest.raises(InvalidOutputError):
        LLM(bad, database, max_attempts=1).call(request, Greeting)

    good = ReplayAdapter({request_key(request): '{"text": "hello"}'})

    assert LLM(good, database).call(request, Greeting).output == Greeting(text="hello")


class Refusing:
    """An adapter refusing its first `refusals` calls, then answering."""

    def __init__(self, refusals: int) -> None:
        self.refusals = refusals
        self.calls = 0

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        self.calls += 1
        if self.calls <= self.refusals:
            raise ModelRefusedError("blocked: reasoning_extraction")
        return RawAnswer('{"text": "hello"}', 10, 5)


def test_a_refusal_is_retried_and_a_later_answer_is_returned(tmp_path: Path) -> None:
    adapter = Refusing(refusals=2)

    result = LLM(adapter, tmp_path / "book.sqlite").call(make_request(), Greeting)

    assert result.output == Greeting(text="hello")
    assert adapter.calls == 3


def test_a_refusal_that_persists_is_saved_and_raised_with_its_context(tmp_path: Path) -> None:
    request = make_request()
    adapter = Refusing(refusals=99)

    with pytest.raises(ModelRefusedError) as stopped:
        LLM(adapter, tmp_path / "book.sqlite").call(request, Greeting)

    assert adapter.calls == 3
    assert stopped.value.stage == request.stage
    assert stopped.value.attempts == 3
    assert "reasoning_extraction" in stopped.value.detail
    assert stopped.value.log == tmp_path / "logs" / f"refused-{request_key(request)}.json"
    assert "reasoning_extraction" in stopped.value.log.read_text()


def test_a_refusal_is_never_cached(tmp_path: Path) -> None:
    database = tmp_path / "book.sqlite"
    with pytest.raises(ModelRefusedError):
        LLM(Refusing(refusals=99), database, max_attempts=1).call(make_request(), Greeting)

    assert LLM(Refusing(refusals=0), database).call(make_request(), Greeting).output.text == "hello"
