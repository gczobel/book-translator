"""The production adapter, built on pydantic-ai. The only module that imports it (ADR 0003)."""

from collections.abc import Callable

from pydantic_ai import Agent
from pydantic_ai.models import Model

from book_translator.llm import LLMRequest, RawAnswer

ModelResolver = Callable[[str], Model | str]


def _use_model_string(name: str) -> str:
    return name


class PydanticAIAdapter:
    """Sends the request to the model named by `request.model` ("provider:model").

    The adapter returns raw text; `LLM` validates it against the schema and retries a bounded
    number of times. `resolve` turns the model string into what pydantic-ai runs; tests pass a
    fake model, production passes the string straight through.
    """

    def __init__(self, resolve: ModelResolver = _use_model_string) -> None:
        self._resolve = resolve

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        agent = Agent(
            self._resolve(request.model),
            instructions=f"{request.prompt}\n\n{request.bible_slice}",
        )
        result = agent.run_sync(request.source_text)
        usage = result.usage
        return RawAnswer(result.output, usage.input_tokens, usage.output_tokens)
