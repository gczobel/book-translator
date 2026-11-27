"""Record mode: call a real adapter under a small spend limit and keep what it answered.

Recordings are a JSON file mapping a request key to the list of raw answers, one per attempt,
which is the shape the replay adapter reads.
"""

import json
from pathlib import Path

from book_translator.llm import Adapter, LLMRequest, RawAnswer, cost_of


class RecordingLimitError(Exception):
    """Recording spent its own limit; it is separate from the per-book cap."""


def load_recordings(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    data: dict[str, list[str]] = json.loads(path.read_text(encoding="utf-8"))
    return data


class RecordingAdapter:
    def __init__(self, inner: Adapter, path: Path, limit_usd: float) -> None:
        self._inner = inner
        self._path = path
        self._limit_usd = limit_usd
        self._spent_usd = 0.0

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if self._spent_usd >= self._limit_usd:
            raise RecordingLimitError(
                f"recording spent ${self._spent_usd:.2f} of its ${self._limit_usd:.2f} limit"
            )
        answer = self._inner.complete(request, key, attempt)
        self._spent_usd += cost_of(request.model, answer.input_tokens, answer.output_tokens)
        recordings = load_recordings(self._path)
        answers = recordings.get(key, []) if attempt else []
        recordings[key] = [*answers[:attempt], answer.text]
        self._path.write_text(json.dumps(recordings, indent=2, sort_keys=True), encoding="utf-8")
        return answer
