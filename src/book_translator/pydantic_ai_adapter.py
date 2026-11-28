"""The production adapter, built on pydantic-ai. The only module that imports it (ADR 0003)."""

from collections.abc import Callable

from pydantic_ai import Agent
from pydantic_ai.exceptions import ContentFilterError
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model

from book_translator.llm import LLMRequest, ModelRefusedError, RawAnswer

ModelResolver = Callable[[str], Model | str]


def _use_model_string(name: str) -> str:
    return name


def _refusal(exc: ContentFilterError) -> ModelRefusedError:
    """The refusal with its category and what the provider billed, read from the failed run."""
    category, input_tokens, output_tokens = "", 0, 0
    conversation = exc.conversation
    for message in reversed(conversation.messages if conversation else []):
        if isinstance(message, ModelResponse):
            category = str((message.provider_details or {}).get("refusal_category", ""))
            input_tokens = message.usage.input_tokens
            output_tokens = message.usage.output_tokens
            break
    return ModelRefusedError(
        exc.message, category=category, input_tokens=input_tokens, output_tokens=output_tokens
    )


class PydanticAIAdapter:
    """Sends the request to the model named by `request.model` ("provider:model").

    The adapter returns raw text; `LLM` validates it against the schema and retries a bounded
    number of times. `resolve` turns the model string into what pydantic-ai runs; tests pass a
    fake model, production passes the string straight through.
    """

    def __init__(self, resolve: ModelResolver = _use_model_string) -> None:
        self._resolve = resolve

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        instructions = f"{request.prompt}\n\n{request.bible_slice}"
        if request.output_schema:
            instructions += (
                "\n\nAnswer with a single JSON object and nothing else, valid against this "
                f"JSON schema:\n{request.output_schema}"
            )
        if request.reworded:
            instructions += (
                "\n\nKeep every explanation or reason field to one short factual sentence about "
                "the text itself. Do not describe your own reasoning process."
            )
        if request.feedback:
            instructions += (
                "\n\nYour previous answer failed validation (validation error below). "
                f"Fix it:\n{request.feedback}"
            )
        agent = Agent(self._resolve(request.model), instructions=instructions)
        try:
            result = agent.run_sync(request.source_text)
        except ContentFilterError as exc:
            raise _refusal(exc) from exc
        usage = result.usage
        return RawAnswer(result.output, usage.input_tokens, usage.output_tokens)
