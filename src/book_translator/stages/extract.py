"""S1, first step: per-chapter extraction of names, places and notable phrases."""

from pydantic import BaseModel

from book_translator.llm import LLMRequest

PROMPT_VERSION = "extract-v1"
_PROMPT = (
    "Read this chapter, whose inline markup is written as numbered codes. List the names of "
    "characters, the places, and the notable phrases (recurring or striking wording) it contains."
)


class Extraction(BaseModel):
    """What one chapter holds: the raw material for the whole-book consolidation."""

    names: list[str]
    places: list[str]
    phrases: list[str]


def extraction_request(model: str, chapter_text: str) -> LLMRequest:
    return LLMRequest(
        stage="extraction",
        prompt_version=PROMPT_VERSION,
        model=model,
        prompt=_PROMPT,
        bible_slice="",
        source_text=chapter_text,
    )
