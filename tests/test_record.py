"""Seam: record mode wraps a (fake) real adapter and writes recordings the replay adapter reads."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from book_translator.llm import LLM, LLMRequest, RawAnswer, request_key
from book_translator.record import RecordingAdapter, RecordingLimitError, load_recordings
from book_translator.replay import ReplayAdapter


class Greeting(BaseModel):
    text: str


class FakeAdapter:
    def __init__(self, answers: list[str], input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.answers = answers
        self.calls = 0
        self._tokens = (input_tokens, output_tokens)

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        text = self.answers[self.calls]
        self.calls += 1
        return RawAnswer(text, *self._tokens)


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


def test_a_recorded_call_is_replayed_by_the_same_input_hash(tmp_path: Path) -> None:
    path = tmp_path / "recordings.json"
    request = make_request()
    recorder = RecordingAdapter(FakeAdapter(['{"text": "hello"}']), path, limit_usd=1.0)
    LLM(recorder, tmp_path / "a.sqlite").call(request, Greeting)

    replay = ReplayAdapter(load_recordings(path))
    result = LLM(replay, tmp_path / "b.sqlite").call(request, Greeting)

    assert result.output == Greeting(text="hello")
    assert request_key(request) in load_recordings(path)


def test_every_attempt_is_recorded_so_retries_replay_too(tmp_path: Path) -> None:
    path = tmp_path / "recordings.json"
    request = make_request()
    recorder = RecordingAdapter(FakeAdapter(["not json", '{"text": "ok"}']), path, limit_usd=1.0)
    LLM(recorder, tmp_path / "a.sqlite").call(request, Greeting)

    result = LLM(ReplayAdapter(load_recordings(path)), tmp_path / "b.sqlite").call(
        request, Greeting
    )

    assert result.output == Greeting(text="ok")


def test_existing_recordings_are_kept_when_recording_more(tmp_path: Path) -> None:
    path = tmp_path / "recordings.json"
    first, second = make_request(), make_request(source_text="Adiós.")
    RecordingAdapter(FakeAdapter(["a"]), path, limit_usd=1.0).complete(first, request_key(first), 0)
    RecordingAdapter(FakeAdapter(["b"]), path, limit_usd=1.0).complete(
        second, request_key(second), 0
    )

    assert set(load_recordings(path)) == {request_key(first), request_key(second)}


def test_recording_stops_at_its_own_spend_limit(tmp_path: Path) -> None:
    path = tmp_path / "recordings.json"
    inner = FakeAdapter(["a", "b"], input_tokens=1_000_000)  # $3 per call on Sonnet
    recorder = RecordingAdapter(inner, path, limit_usd=2.0)
    first, second = make_request(), make_request(source_text="Adiós.")
    recorder.complete(first, request_key(first), 0)

    with pytest.raises(RecordingLimitError):
        recorder.complete(second, request_key(second), 0)

    assert inner.calls == 1
