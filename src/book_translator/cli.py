"""Command-line interface. Only `init` exists so far."""

import argparse
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
from book_translator.estimate import estimate
from book_translator.gates import GateError, approve_waiting_gate
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
    run_cmd = sub.add_parser("run", help="advance the book through its stages (resumable)")
    run_cmd.add_argument("workspace", type=Path)
    run_cmd.add_argument("--cap", type=float, help="set a new spending cap in USD before running")
    status_cmd = sub.add_parser("status", help="show the stage, progress and spend of a workspace")
    status_cmd.add_argument("workspace", type=Path)
    approve_cmd = sub.add_parser("approve", help="approve the waiting review gate")
    approve_cmd.add_argument("workspace", type=Path)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    adapter: Adapter | None = None,
    search: Search | None = None,
) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        _init(args)
    elif args.command == "run":
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
    elif args.command == "status":
        if not (args.workspace / workspace.DB_NAME).is_file():
            sys.exit(f"error: not a workspace: {args.workspace}")
        print(render(read_status(args.workspace), args.workspace))
    else:
        parser.print_help()


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
