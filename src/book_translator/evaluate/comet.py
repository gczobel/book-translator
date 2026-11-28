"""The COMET seam. COMET (unbabel-comet) needs older ML libraries than the `evaluate` extra, so it
never shares an environment with this project: the real scorer starts it through `uv` in a
throwaway environment, with its version pinned here. It is a local tool: nothing here runs in CI,
and the model (about 2 GB) is downloaded by COMET on the first use. Tests hand `evaluate` a fake
scorer and never start it."""

import json
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

COMET_VERSION = "2.2.7"
COMET_MODEL = "Unbabel/wmt22-comet-da"
# COMET 2.2.7 does not start on the project's Python 3.13 (its argument parser), and it imports
# `pkg_resources`, which setuptools 81 and later no longer ship. Its own command line does not
# work on current Python releases at all, so the script below uses its Python interface.
COMET_PYTHON = "3.12"
COMET_SETUPTOOLS = "setuptools<81"

Triple = tuple[str, str, str]  # (source, our translation, reference translation)

_SCRIPT = f"""\
import json, sys
import torch
from comet import download_model, load_from_checkpoint

data = json.load(open(sys.argv[1]))
model = load_from_checkpoint(download_model({COMET_MODEL!r}))
gpus = 1 if torch.cuda.is_available() else 0
out = model.predict(data, batch_size=8, gpus=gpus, progress_bar=False)
json.dump({{"scores": out.scores}}, open(sys.argv[2], "w"))
"""


class CometError(Exception):
    pass


class CometScorer(Protocol):
    def score(self, triples: Sequence[Triple]) -> list[float]:
        """One score per triple, about 0 to 1: how close our translation is to the reference,
        read against the source."""
        ...


class UvCometScorer:
    """COMET run in its own environment, started with `uv run --with unbabel-comet==...`."""

    def score(self, triples: Sequence[Triple]) -> list[float]:
        if not triples:
            return []
        with tempfile.TemporaryDirectory(prefix="comet-") as folder:
            work = Path(folder)
            (work / "score.py").write_text(_SCRIPT, encoding="utf-8")
            (work / "in.json").write_text(
                json.dumps([{"src": s, "mt": m, "ref": r} for s, m, r in triples]),
                encoding="utf-8",
            )
            command = [
                "uv",
                "run",
                "--no-project",
                "--python",
                COMET_PYTHON,
                "--with",
                f"unbabel-comet=={COMET_VERSION}",
                "--with",
                COMET_SETUPTOOLS,
                "python",
                str(work / "score.py"),
                str(work / "in.json"),
                str(work / "out.json"),
            ]
            try:
                done = subprocess.run(command, capture_output=True, text=True, check=False)
            except FileNotFoundError as exc:
                raise CometError(
                    "--comet needs `uv` on the PATH: it starts COMET in its own environment"
                ) from exc
            if done.returncode != 0:
                tail = " ".join(done.stderr.split()[-60:])
                raise CometError(f"COMET failed (exit {done.returncode}): ...{tail}")
            scores = json.loads((work / "out.json").read_text(encoding="utf-8"))["scores"]
        if len(scores) != len(triples):
            raise CometError(f"COMET returned {len(scores)} scores for {len(triples)} segments")
        return [float(s) for s in scores]
