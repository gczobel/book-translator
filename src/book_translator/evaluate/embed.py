"""The embedding seam. The real model (LaBSE) is an optional dependency, loaded lazily; tests
hand `evaluate` a fake `Embedder` and never download a model."""

from collections.abc import Sequence
from typing import Any, Protocol

LABSE_MODEL = "sentence-transformers/LaBSE"


class EmbeddingsUnavailableError(Exception):
    pass


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text; texts with the same meaning in any language land close."""
        ...


class LaBSEEmbedder:
    """LaBSE through sentence-transformers, imported and loaded on first use."""

    def __init__(self) -> None:
        self._model: Any = None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingsUnavailableError(
                    "evaluate needs the LaBSE embedding model: install the optional group with"
                    " `uv sync --extra evaluate` (it pulls in sentence-transformers and torch)"
                ) from exc
            self._model = SentenceTransformer(LABSE_MODEL)
        vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return [[float(x) for x in row] for row in vectors]
