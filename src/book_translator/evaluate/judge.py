"""The evaluation-only LLM stages: the judge (errors by type and severity per scene) and the
diagnosis (likely causes and fixes, given the report).

Both go through the same `LLM` as the translation stages, so they are budget-guarded and cached
by request: a rerun repeats no call. Nothing here is imported by a translation stage (ADR 0004).
"""

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from book_translator.llm import LLM, LLMRequest

JUDGE_PROMPT_VERSION = "judge-v1"
DIAGNOSIS_PROMPT_VERSION = "diagnosis-v1"
_JUDGE_PROMPT = (
    "You are a translation quality judge. Compare our translation of the scene with the "
    "reference translation and the source. Mark each error in ours with a type and a severity "
    "(minor, major or critical) and a short note. Return no marks for a faithful scene."
)
_DIAGNOSIS_PROMPT = (
    "Given this quality report of a machine translation (QA failures, per-chapter scores, error "
    "counts, and what each stage changed), list the likely causes of the problems and, for each, "
    "a suggested fix to the pipeline."
)

ErrorType = Literal[
    "accuracy",
    "omission",
    "addition",
    "fluency",
    "terminology",
    "register",
    "address",
    "typography",
    "other",
]
Severity = Literal["minor", "major", "critical"]


class Mark(BaseModel):
    type: ErrorType
    severity: Severity
    note: str = ""


class SceneMarks(BaseModel):
    marks: list[Mark] = []


class Cause(BaseModel):
    cause: str
    fix: str


class Diagnosis(BaseModel):
    diagnosis: list[Cause] = []


@dataclass(frozen=True)
class SceneView:
    """One of our scenes with its source and its aligned reference text."""

    chapter: int  # 1-based
    scene: int  # 1-based
    source: str
    ours: str
    reference: str


def judge_scenes(llm: LLM, model: str, scenes: list[SceneView]) -> dict[str, Any]:
    """Mark every scene; returns the report's `judge` section."""
    per_scene: list[dict[str, Any]] = []
    for view in scenes:
        request = LLMRequest(
            stage="judge",
            prompt_version=JUDGE_PROMPT_VERSION,
            model=model,
            prompt=_JUDGE_PROMPT,
            bible_slice="",
            source_text=json.dumps(
                {"source": view.source, "ours": view.ours, "reference": view.reference},
                ensure_ascii=False,
            ),
        )
        marks = llm.call(request, SceneMarks).output.marks
        per_scene.append(
            {
                "chapter": view.chapter,
                "scene": view.scene,
                "marks": [m.model_dump() for m in marks],
            }
        )
    every = [m for s in per_scene for m in s["marks"]]
    return {
        "model": model,
        "by_type": dict(sorted(Counter(m["type"] for m in every).items())),
        "by_severity": dict(sorted(Counter(m["severity"] for m in every).items())),
        "scenes": per_scene,
    }


def diagnose(llm: LLM, model: str, report: dict[str, Any]) -> list[dict[str, str]]:
    """Likely causes and suggested fixes for what the report shows."""
    request = LLMRequest(
        stage="diagnosis",
        prompt_version=DIAGNOSIS_PROMPT_VERSION,
        model=model,
        prompt=_DIAGNOSIS_PROMPT,
        bible_slice="",
        source_text=json.dumps(report, ensure_ascii=False, sort_keys=True),
    )
    return [c.model_dump() for c in llm.call(request, Diagnosis).output.diagnosis]
