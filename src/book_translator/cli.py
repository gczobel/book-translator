"""Command-line interface. Only `init` exists so far."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from book_translator import workspace
from book_translator.budget import CapReachedError, set_cap
from book_translator.config import (
    DEFAULT_CAP_USD,
    DEFAULT_FIDELITY_RETRIES,
    PROVIDER_KEYS,
    STAGE_MODELS,
    VARIETIES,
)
from book_translator.epub import open_epub
from book_translator.epubcheck import EpubcheckNotFoundError
from book_translator.estimate import estimate
from book_translator.evaluate import REPORT_MD, EvaluateError, evaluate
from book_translator.evaluate.comet import CometScorer, CometUnavailableError, UnbabelComet
from book_translator.evaluate.embed import Embedder, EmbeddingsUnavailableError, LaBSEEmbedder
from book_translator.export import REPORT_NAME, ExportError, ValidationFailedError, export
from book_translator.fonts import FontCoverageError
from book_translator.gates import GateError, approve_waiting_gate
from book_translator.inline import InlineCodeError
from book_translator.llm import Adapter
from book_translator.pydantic_ai_adapter import PydanticAIAdapter
from book_translator.qa import print_report
from book_translator.review import ReviewError
from book_translator.run import run
from book_translator.search import Search, WikiSearch
from book_translator.status import read_status, render
from book_translator.structure import Book


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="book-translator")
    sub = parser.add_subparsers(dest="command")
    init = sub.add_parser("init", help="create a workspace for a book and show the estimate")
    init.add_argument("epub", type=Path)
    init.add_argument("--variety", required=True, choices=VARIETIES, help="target Spanish variety")
    init.add_argument("--target", default="es", help="target language (default: es)")
    init.add_argument("--cap", type=float, default=DEFAULT_CAP_USD, help="spending cap in USD")
    init.add_argument("--workspace", type=Path, help="workspace folder (default: ./<epub name>)")
    init.add_argument(
        "--evaluation",
        action="store_true",
        help="evaluation run: no established-terminology lookups (ADR 0004)",
    )
    init.add_argument(
        "--skip-analysis-gate",
        action="store_true",
        help="unattended run: accept every recommendation instead of stopping for review",
    )
    init.add_argument(
        "--fidelity-retries",
        type=int,
        default=DEFAULT_FIDELITY_RETRIES,
        help="times to correct and re-check a scene the polish made drift (default: 2)",
    )
    init.add_argument(
        "--qa-length-band",
        type=float,
        nargs=2,
        metavar=("MIN", "MAX"),
        help="QA: allowed target/source length ratio per block (default: 0.5 2.0)",
    )
    run_cmd = sub.add_parser("run", help="advance the book through its stages (resumable)")
    run_cmd.add_argument("workspace", type=Path)
    run_cmd.add_argument("--cap", type=float, help="set a new spending cap in USD before running")
    status_cmd = sub.add_parser("status", help="show the stage, progress and spend of a workspace")
    status_cmd.add_argument("workspace", type=Path)
    approve_cmd = sub.add_parser("approve", help="approve the waiting review gate")
    approve_cmd.add_argument("workspace", type=Path)
    export_cmd = sub.add_parser("export", help="build the translated EPUB and validate it")
    export_cmd.add_argument("workspace", type=Path)
    evaluate_cmd = sub.add_parser(
        "evaluate", help="compare the exported EPUB with a reference translation"
    )
    evaluate_cmd.add_argument("workspace", type=Path)
    evaluate_cmd.add_argument("--reference", type=Path, required=True, help="reference EPUB")
    evaluate_cmd.add_argument(
        "--judge", action="store_true", help="LLM judge: errors by type and severity per scene"
    )
    evaluate_cmd.add_argument(
        "--comet", action="store_true", help="also score with COMET (needs unbabel-comet)"
    )
    evaluate_cmd.add_argument(
        "--diagnose", action="store_true", help="LLM diagnosis: likely causes and suggested fixes"
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    adapter: Adapter | None = None,
    search: Search | None = None,
    embedder: Embedder | None = None,
    comet: CometScorer | None = None,
) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        _init(args)
    elif args.command == "run":
        if not (args.workspace / workspace.DB_NAME).is_file():
            sys.exit(f"error: not a workspace: {args.workspace}")
        if adapter is None:
            adapter = _production_adapter()
            if search is None:
                search = WikiSearch()
        if args.cap is not None:
            set_cap(args.workspace / workspace.DB_NAME, args.cap)
        try:
            run(args.workspace, adapter, search)
        except CapReachedError as exc:
            sys.exit(f"stopped: {exc}")
        print_report(args.workspace)
    elif args.command == "approve":
        _approve(args.workspace)
    elif args.command == "export":
        _export(args.workspace)
    elif args.command == "evaluate":
        _evaluate(args, adapter, embedder or LaBSEEmbedder(), comet)
    elif args.command == "status":
        if not (args.workspace / workspace.DB_NAME).is_file():
            sys.exit(f"error: not a workspace: {args.workspace}")
        print(render(read_status(args.workspace), args.workspace))
    else:
        parser.print_help()


def _export(path: Path) -> None:
    if not (path / workspace.DB_NAME).is_file():
        sys.exit(f"error: not a workspace: {path}")
    try:
        out = export(path)
    except ValidationFailedError as exc:
        print(exc.report, end="")
        sys.exit("error: epubcheck failed; the report is in " + str(path / REPORT_NAME))
    except (ExportError, EpubcheckNotFoundError, FontCoverageError, InlineCodeError) as exc:
        sys.exit(f"error: {exc}")
    print(f"Exported: {out}\nepubcheck report: {path / REPORT_NAME}")


def _evaluate(
    args: argparse.Namespace,
    adapter: Adapter | None,
    embedder: Embedder,
    comet: CometScorer | None,
) -> None:
    path: Path = args.workspace
    if not (path / workspace.DB_NAME).is_file():
        sys.exit(f"error: not a workspace: {path}")
    if (args.judge or args.diagnose) and adapter is None:
        adapter = _production_adapter()
    try:
        out = evaluate(
            path,
            args.reference,
            embedder,
            adapter=adapter,
            judge=args.judge,
            diagnose=args.diagnose,
            comet=(comet or UnbabelComet()) if args.comet else None,
        )
    except (EvaluateError, EmbeddingsUnavailableError, CometUnavailableError) as exc:
        sys.exit(f"error: {exc}")
    except CapReachedError as exc:
        sys.exit(f"stopped: {exc}")
    if not json.loads(out.read_text())["evaluation_mode"]:
        print(
            "warning: this workspace was not initialised with `init --evaluation`, so"
            " established-terminology lookups may have used the web; scores may be inflated",
            file=sys.stderr,
        )
    print(f"Quality report: {out}\nReadable copy: {path / REPORT_MD}")


def _production_adapter() -> Adapter:
    """The pydantic-ai adapter; each provider's key must be in the environment."""
    providers = sorted({model.split(":", 1)[0] for model in STAGE_MODELS.values()})
    missing = [PROVIDER_KEYS[p] for p in providers if not os.environ.get(PROVIDER_KEYS[p])]
    if missing:
        sys.exit(f"error: set {', '.join(missing)} in the environment to call the LLM")
    return PydanticAIAdapter()


def _init(args: argparse.Namespace) -> None:
    epub: Path = args.epub
    try:
        book = open_epub(epub).book()
    except Exception as exc:  # any unreadable or malformed file
        sys.exit(f"error: cannot read {epub} as an EPUB: {exc}")
    path: Path = args.workspace or Path(epub.stem)
    settings = {"variety": args.variety, "target": args.target, "cap_usd": f"{args.cap:.2f}"}
    settings["fidelity_retries"] = str(max(args.fidelity_retries, 0))
    if args.qa_length_band:
        settings["qa_length_band"] = ",".join(str(v) for v in args.qa_length_band)
    if args.evaluation:
        settings["evaluation"] = "1"
    if args.skip_analysis_gate:
        settings["skip_analysis_gate"] = "1"
    try:
        workspace.create(path, epub, settings)
    except workspace.WorkspaceError as exc:
        sys.exit(f"error: {exc}")
    print(f"Workspace: {path}")
    _print_structure(book)
    est = estimate(book)
    print(f"Estimated cost: ${est.cost_usd:.2f} for {est.words} words (cap ${args.cap:.2f})")
    print("No LLM has been called.")


def _print_structure(book: Book) -> None:
    print(f"Structure: {len(book.chapters)} chapters")
    for i, chapter in enumerate(book.chapters, 1):
        words = sum(len(b.text.split()) for s in chapter.scenes for b in s.blocks)
        print(
            f"  {i}. {chapter.title or '(untitled)'}: {len(chapter.scenes)} scenes, {words} words"
        )
    for label, parts in (("Front matter", book.front), ("Back matter", book.back)):
        if parts:
            print(f"{label}: " + ", ".join(p.kind for p in parts))


def _approve(path: Path) -> None:
    if not (path / workspace.DB_NAME).is_file():
        sys.exit(f"error: not a workspace: {path}")
    try:
        approve_waiting_gate(path)
    except (GateError, ReviewError) as exc:
        sys.exit(f"error: {exc}")
    print(f"Approved. Next: book-translator run {path}")
