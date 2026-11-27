"""The replay adapter: serves recorded raw answers by input hash, never touching the network."""

from collections.abc import Mapping, Sequence

from book_translator.llm import LLMRequest, RawAnswer


class MissingRecordingError(Exception):
    pass


class ReplayAdapter:
    """Recordings map a request key to one raw answer, or to a list used one per attempt."""

    def __init__(self, recordings: Mapping[str, str | Sequence[str]]) -> None:
        self._recordings = recordings

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if key not in self._recordings:
            raise MissingRecordingError(f"no recording for key {key} (stage {request.stage})")
        recorded = self._recordings[key]
        if isinstance(recorded, str):
            return RawAnswer(recorded)
        return RawAnswer(recorded[min(attempt, len(recorded) - 1)])
