"""Seam 3: the LLM interface, observed through the replay adapter and the call cache."""

from pathlib import Path

import pytest
from pydantic import BaseModel

from book_translator.llm import LLM, LLMRequest, request_key
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
