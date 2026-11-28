"""Seam: the pydantic-ai adapter, driven by pydantic-ai's function model (never a real API)."""

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ThinkingPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from book_translator.llm import LLM, LLMRequest, ModelRefusedError
from book_translator.pydantic_ai_adapter import PydanticAIAdapter


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


def scripted(answers: list[str], seen: list[str] | None = None) -> FunctionModel:
    """A fake model returning the next scripted answer per call."""
    calls = iter(answers)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.append(repr(messages))
        return ModelResponse(parts=[TextPart(next(calls))])

    return FunctionModel(respond)


def test_the_adapter_returns_the_model_text_and_its_tokens() -> None:
    model = scripted(['{"text": "hello"}'])
    adapter = PydanticAIAdapter(lambda name: model)

    answer = adapter.complete(make_request(), "key", 0)

    assert answer.text == '{"text": "hello"}'
    assert answer.input_tokens > 0
    assert answer.output_tokens > 0


def test_the_prompt_bible_and_source_reach_the_model() -> None:
    seen: list[str] = []
    adapter = PydanticAIAdapter(lambda name: scripted(["{}"], seen))

    request = make_request(prompt="PROMPT", bible_slice="BIBLE", source_text="SOURCE")
    adapter.complete(request, "k", 0)

    assert all(word in seen[0] for word in ("PROMPT", "BIBLE", "SOURCE"))


def test_the_model_string_comes_from_the_request_so_a_provider_change_is_config_only() -> None:
    names: list[str] = []

    def resolve(name: str) -> Model:
        names.append(name)
        return scripted(["{}"])

    adapter = PydanticAIAdapter(resolve)

    adapter.complete(make_request(model="openrouter:some/model"), "k", 0)

    assert names == ["openrouter:some/model"]


def test_invalid_output_is_retried_a_bounded_number_of_times(tmp_path: Path) -> None:
    model = scripted(["not json", '{"text": "ok"}'])
    llm = LLM(PydanticAIAdapter(lambda name: model), tmp_path / "b.sqlite", max_attempts=2)

    result = llm.call(make_request(), Greeting)

    assert result.output == Greeting(text="ok")


def test_the_model_is_told_the_output_schema(tmp_path: Path) -> None:
    seen: list[str] = []
    model = scripted(['{"text": "ok"}'], seen)
    llm = LLM(PydanticAIAdapter(lambda name: model), tmp_path / "b.sqlite")

    llm.call(make_request(), Greeting)

    assert '"text"' in seen[0]
    assert "schema" in seen[0].lower()


def test_a_fenced_json_answer_is_accepted(tmp_path: Path) -> None:
    model = scripted(['```json\n{"text": "ok"}\n```'])
    llm = LLM(PydanticAIAdapter(lambda name: model), tmp_path / "b.sqlite", max_attempts=1)

    assert llm.call(make_request(), Greeting).output == Greeting(text="ok")


def test_a_retry_tells_the_model_what_was_wrong(tmp_path: Path) -> None:
    seen: list[str] = []
    model = scripted(['{"wrong": 1}', '{"text": "ok"}'], seen)
    llm = LLM(PydanticAIAdapter(lambda name: model), tmp_path / "b.sqlite", max_attempts=2)

    llm.call(make_request(), Greeting)

    assert "validation error" in seen[1].lower()
    assert "validation error" not in seen[0].lower()


def test_a_refusal_by_the_provider_becomes_our_own_error_with_its_text() -> None:
    def refuse(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ThinkingPart(content="")],
            finish_reason="content_filter",
            provider_details={"refusal": "blocked: reasoning_extraction"},
        )

    adapter = PydanticAIAdapter(lambda name: FunctionModel(refuse))

    with pytest.raises(ModelRefusedError, match="reasoning_extraction"):
        adapter.complete(make_request(), "k", 0)


def test_a_refusal_carries_its_category_and_the_tokens_the_provider_billed() -> None:
    def refuse(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[],
            usage=RequestUsage(input_tokens=15641, output_tokens=1410),
            finish_reason="content_filter",
            provider_details={"refusal": "no", "refusal_category": "reasoning_extraction"},
        )

    adapter = PydanticAIAdapter(lambda name: FunctionModel(refuse))

    with pytest.raises(ModelRefusedError) as stopped:
        adapter.complete(make_request(), "k", 0)

    assert stopped.value.category == "reasoning_extraction"
    assert (stopped.value.input_tokens, stopped.value.output_tokens) == (15641, 1410)


def test_a_reworded_request_asks_for_short_factual_reasons() -> None:
    seen: list[str] = []

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(str(info.instructions))
        return ModelResponse(parts=[TextPart(content='{"text": "hi"}')])

    adapter = PydanticAIAdapter(lambda name: FunctionModel(answer))
    adapter.complete(make_request(), "k", 0)
    adapter.complete(replace(make_request(), reworded=True), "k", 0)

    assert "own reasoning process" not in seen[0]
    assert "own reasoning process" in seen[1]
