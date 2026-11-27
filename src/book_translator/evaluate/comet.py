"""The COMET seam. COMET runs only behind `evaluate --comet`. The real model comes from the
optional `unbabel-comet` package, imported and downloaded on first use; tests hand `evaluate` a
fake `CometScorer` and never load a model."""

from collections.abc import Sequence
from typing import Any, Protocol

from book_translator.evaluate.judge import SceneView

COMET_MODEL = "Unbabel/wmt22-comet-da"


class CometUnavailableError(Exception):
    pass


class CometScorer(Protocol):
    def score(self, triples: Sequence[tuple[str, str, str]]) -> list[float]:
        """One score per (source, translation, reference) triple; higher is better."""
        ...


class UnbabelComet:
    """COMET through unbabel-comet, imported and loaded on first use."""

    def __init__(self) -> None:
        self._model: Any = None

    def score(self, triples: Sequence[tuple[str, str, str]]) -> list[float]:
        if self._model is None:
            try:
                from comet import download_model, load_from_checkpoint
            except ImportError as exc:
                raise CometUnavailableError(
                    "--comet needs the optional `unbabel-comet` package (it pulls in torch):"
                    " install it with `uv pip install unbabel-comet`"
                ) from exc
            self._model = load_from_checkpoint(download_model(COMET_MODEL))
        data = [{"src": s, "mt": m, "ref": r} for s, m, r in triples]
        output = self._model.predict(data, batch_size=8, gpus=0)
        return [float(x) for x in output.scores]


def comet_scores(scorer: CometScorer, scenes: Sequence[SceneView]) -> dict[str, Any]:
    """Per-scene COMET and their mean; scenes with no reference counterpart are left out."""
    scored = [v for v in scenes if v.reference]
    scores = scorer.score([(v.source, v.ours, v.reference) for v in scored]) if scored else []
    per_scene = [
        {"chapter": v.chapter, "scene": v.scene, "score": round(s, 4)}
        for v, s in zip(scored, scores, strict=True)
    ]
    mean = sum(s["score"] for s in per_scene) / len(per_scene) if per_scene else None
    return {"model": COMET_MODEL, "overall": mean, "scenes": per_scene}
