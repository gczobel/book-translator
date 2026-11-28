"""Seam 3: the LLM interface, observed through the replay adapter and the call cache."""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from book_translator.budget import Budget
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


def make_request(**overrides: Any) -> LLMRequest:
    fields: dict[str, Any] = {
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
    """An adapter that refuses the calls its `refuse` function says to, and answers the rest.
    `seen` keeps each request it was sent."""

    def __init__(self, refuse: Callable[[LLMRequest, int], bool], category: str = "") -> None:
        self.refuse = refuse
        self.category = category
        self.seen: list[LLMRequest] = []

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        self.seen.append(request)
        if self.refuse(request, len(self.seen)):
            raise ModelRefusedError(
                f"blocked: {self.category}", category=self.category, input_tokens=1000
            )
        return RawAnswer('{"text": "hello"}', 10, 5)


def always(request: LLMRequest, call: int) -> bool:
    return True


SONNET, OPUS = "anthropic:claude-sonnet-5-5", "anthropic:claude-opus-5-5"


def test_a_reasoning_refusal_is_retried_reworded_and_then_answered(tmp_path: Path) -> None:
    adapter = Refusing(lambda r, n: n == 1, "reasoning_extraction")

    result = LLM(adapter, tmp_path / "book.sqlite").call(make_request(), Greeting)

    assert result.output == Greeting(text="hello")
    assert [r.reworded for r in adapter.seen] == [False, True]
    assert [r.model for r in adapter.seen] == [SONNET, SONNET]  # same model, plainer ask


def test_a_reworded_ask_that_is_still_refused_goes_to_the_fallback_model(tmp_path: Path) -> None:
    adapter = Refusing(lambda r, n: r.model == SONNET, "reasoning_extraction")

    result = LLM(adapter, tmp_path / "book.sqlite").call(make_request(), Greeting)

    assert result.output == Greeting(text="hello")
    assert [(r.model, r.reworded) for r in adapter.seen] == [
        (SONNET, False),
        (SONNET, True),
        (OPUS, True),
    ]


def test_an_invalid_answer_does_not_use_up_the_attempts_for_the_fallback_model(
    tmp_path: Path,
) -> None:
    """Issue 168: one invalid answer, then two refusals, ended the loop before the fallback ran."""

    class InvalidThenRefusing:
        def __init__(self) -> None:
            self.seen: list[LLMRequest] = []

        def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
            self.seen.append(request)
            if len(self.seen) == 1:
                return RawAnswer("not json", 10, 5)
            if request.model == SONNET:
                raise ModelRefusedError("blocked", category="reasoning_extraction")
            return RawAnswer('{"text": "hello"}', 10, 5)

    adapter = InvalidThenRefusing()

    result = LLM(adapter, tmp_path / "book.sqlite").call(make_request(), Greeting)

    assert result.output == Greeting(text="hello")
    assert [(r.model, r.reworded) for r in adapter.seen] == [
        (SONNET, False),
        (SONNET, False),
        (SONNET, True),
        (OPUS, True),
    ]


def test_another_category_goes_straight_to_the_fallback_model(tmp_path: Path) -> None:
    adapter = Refusing(lambda r, n: r.model == SONNET, "general_harms")

    LLM(adapter, tmp_path / "book.sqlite").call(make_request(), Greeting)

    assert [(r.model, r.reworded) for r in adapter.seen] == [(SONNET, False), (OPUS, False)]


def test_when_everything_is_refused_it_stops_with_what_was_tried(tmp_path: Path) -> None:
    request = make_request()
    adapter = Refusing(always, "reasoning_extraction")

    with pytest.raises(ModelRefusedError) as stopped:
        LLM(adapter, tmp_path / "book.sqlite").call(request, Greeting)

    assert len(adapter.seen) == 3  # as asked, reworded, fallback model: never the same ask twice
    assert stopped.value.stage == request.stage
    assert stopped.value.attempts == 3
    assert stopped.value.category == "reasoning_extraction"
    assert stopped.value.log is not None
    text = stopped.value.log.read_text()
    assert "sonnet" in text and "reworded" in text and "opus" in text
    assert stopped.value.log == tmp_path / "logs" / f"refused-{request_key(request)}.json"


def test_a_refusal_with_no_fallback_model_stops_without_resending(tmp_path: Path) -> None:
    adapter = Refusing(always, "general_harms")

    with pytest.raises(ModelRefusedError):
        LLM(adapter, tmp_path / "book.sqlite", fallbacks={}).call(make_request(), Greeting)

    assert len(adapter.seen) == 1


def test_the_answer_of_the_fallback_model_is_costed_at_its_own_price(tmp_path: Path) -> None:
    adapter = Refusing(lambda r, n: r.model == SONNET, "general_harms")

    result = LLM(adapter, tmp_path / "book.sqlite").call(make_request(), Greeting)

    assert result.usage.cost_usd == pytest.approx((10 * 5.0 + 5 * 25.0) / 1e6)


def test_a_billed_refusal_counts_against_the_cap_and_a_free_one_does_not(tmp_path: Path) -> None:
    database = tmp_path / "book.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("create table settings (key text primary key, value text not null)")
        db.execute("insert into settings values ('cap_usd', '10.00')")
    budget = Budget(database)

    LLM(Refusing(lambda r, n: n == 1, "general_harms"), database, budget=budget).call(
        make_request(), Greeting
    )
    after_free = budget.spent()
    LLM(Refusing(lambda r, n: n == 1, "reasoning_extraction"), database, budget=budget).call(
        make_request(source_text="otra"), Greeting
    )

    refused_cost = 1000 * 3.0 / 1e6  # the refused sonnet call: 1000 input tokens
    answered = (10 * 3.0 + 5 * 15.0) / 1e6
    assert after_free == pytest.approx((10 * 5.0 + 5 * 25.0) / 1e6)  # only the fallback's answer
    assert budget.spent() - after_free == pytest.approx(refused_cost + answered)


def test_a_refusal_is_never_cached(tmp_path: Path) -> None:
    database = tmp_path / "book.sqlite"
    with pytest.raises(ModelRefusedError):
        LLM(Refusing(always), database, max_attempts=1).call(make_request(), Greeting)

    assert (
        LLM(Refusing(lambda r, n: False), database).call(make_request(), Greeting).output.text
        == "hello"
    )
