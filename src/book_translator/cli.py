"""Command-line interface: init, run, status, approve, waive, unwaive, export and evaluate."""

import argparse
import json
import os
import sqlite3
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
from book_translator.epub import EpubError, open_epub
from book_translator.epubcheck import EpubcheckNotFoundError
from book_translator.estimate import estimate
from book_translator.evaluate import REPORT_MD, EvaluateError, evaluate
from book_translator.evaluate.comet import CometError, CometScorer, UvCometScorer
from book_translator.evaluate.embed import Embedder, EmbeddingsUnavailableError, LaBSEEmbedder
from book_translator.export import REPORT_NAME, ExportError, ValidationFailedError, export
from book_translator.fonts import FontCoverageError
from book_translator.gates import GateError, approve_waiting_gate
from book_translator.inline import InlineCodeError
from book_translator.llm import (
    Adapter,
    InvalidOutputError,
    LLMRequest,
    ModelRefusedError,
    RawAnswer,
)
from book_translator.progress import Progress
from book_translator.pydantic_ai_adapter import PydanticAIAdapter
from book_translator.qa import WaiverError, print_report, unwaive, waive
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
    run_cmd.add_argument(
        "--quiet", action="store_true", help="do not print progress lines on stderr"
    )
    status_cmd = sub.add_parser("status", help="show the stage, progress and spend of a workspace")
    status_cmd.add_argument("workspace", type=Path)
    approve_cmd = sub.add_parser("approve", help="approve the waiting review gate")
    approve_cmd.add_argument("workspace", type=Path)
    approve_cmd.add_argument(
        "--choices",
        type=Path,
        help="JSON file {card id: choice}; open cards also accept free text",
    )
    waive_cmd = sub.add_parser(
        "waive", help="accept QA findings you have looked at, so they stop blocking the build"
    )
    waive_cmd.add_argument("workspace", type=Path)
    waive_cmd.add_argument("check", help="the check that reported them, e.g. numbers")
    waive_cmd.add_argument("blocks", nargs="+", help="the block ids to accept it for")
    waive_cmd.add_argument("--reason", default="", help="why it is fine (kept in the report)")
    unwaive_cmd = sub.add_parser(
        "unwaive", help="take back a waiver, so the finding blocks the build again"
    )
    unwaive_cmd.add_argument("workspace", type=Path)
    unwaive_cmd.add_argument("check", help="the check the finding was waived for")
    unwaive_cmd.add_argument("blocks", nargs="+", help="the block ids to reopen it for")
    export_cmd = sub.add_parser("export", help="build the translated EPUB and validate it")
    export_cmd.add_argument("workspace", type=Path)
    evaluate_cmd = sub.add_parser(
        "evaluate", help="compare the exported EPUB with a reference translation"
    )
    evaluate_cmd.add_argument("workspace", type=Path)
    evaluate_cmd.add_argument("--reference", type=Path, required=True, help="reference EPUB")
    evaluate_cmd.add_argument(
        "--comet",
        action="store_true",
        help="also score with COMET (local only: started through uv; downloads a ~2 GB model)",
    )
    evaluate_cmd.add_argument(
        "--judge", action="store_true", help="LLM judge: errors by type and severity per scene"
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
            with workspace.locked(args.workspace):
                run(args.workspace, adapter, search, Progress(None, quiet=args.quiet))
        except workspace.WorkspaceBusyError as exc:
            sys.exit(f"error: {exc}; wait for it to finish, or stop it, then run again")
        except CapReachedError as exc:
            sys.exit(f"stopped: {exc}")
        except InvalidOutputError as exc:
            sys.exit(_invalid_message(exc, args.workspace))
        except ModelRefusedError as exc:
            sys.exit(_refused_message(exc, args.workspace))
        print_report(args.workspace)
    elif args.command == "approve":
        _approve(args.workspace, args.choices)
    elif args.command == "waive":
        _waive(args)
    elif args.command == "unwaive":
        _unwaive(args)
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


def _refused_message(exc: ModelRefusedError, path: Path) -> str:
    """A short account of a refusal: where, the provider's words, what was kept, how to go on."""
    detail = " ".join(exc.detail.split())
    if len(detail) > 600:
        detail = detail[:600] + "..."
    where = f" (stage {exc.stage})" if exc.stage else ""
    saved = f"The refusal is saved in {exc.log}." if exc.log else "The refusal could not be saved."
    return (
        f"error: the model refused the request after {exc.attempts} attempt(s){where}: "
        f"{detail}\n{saved}\n"
        "Refusals can be false positives, so trying again may pass.\n"
        f"Work done so far is kept; resume with: book-translator run {path}"
    )


def _invalid_message(exc: InvalidOutputError, path: Path) -> str:
    """A short account of an answer that stayed invalid: where, why, what was kept, how to go on."""
    detail = " ".join(exc.detail.split())
    if len(detail) > 600:
        detail = detail[:600] + "..."
    where = f" (stage {exc.stage})" if exc.stage else ""
    saved = (
        f"The model's last answer is saved in {exc.log}."
        if exc.log
        else "The model's last answer could not be saved."
    )
    return (
        f"error: the model's answer failed validation after {exc.attempts} attempt(s){where}: "
        f"{detail}\n{saved}\n"
        f"Work done so far is kept; resume with: book-translator run {path}"
    )


def _waive(args: argparse.Namespace) -> None:
    if not (args.workspace / workspace.DB_NAME).is_file():
        sys.exit(f"error: not a workspace: {args.workspace}")
    db = sqlite3.connect(args.workspace / workspace.DB_NAME)
    try:
        count = waive(db, args.check, args.blocks, args.reason)
    except WaiverError as exc:
        sys.exit(f"error: {exc}")
    finally:
        db.close()
    print(
        f"{count} finding(s) accepted. They stay in the report; they come back if the block's"
        " text changes. Run book-translator run to re-check."
    )


def _unwaive(args: argparse.Namespace) -> None:
    if not (args.workspace / workspace.DB_NAME).is_file():
        sys.exit(f"error: not a workspace: {args.workspace}")
    db = sqlite3.connect(args.workspace / workspace.DB_NAME)
    try:
        count = unwaive(db, args.check, args.blocks)
    except WaiverError as exc:
        sys.exit(f"error: {exc}")
    finally:
        db.close()
    print(f"{count} finding(s) reopened. They block the build until fixed or waived again.")


def _export(path: Path) -> None:
    if not (path / workspace.DB_NAME).is_file():
        sys.exit(f"error: not a workspace: {path}")
    try:
        out = export(path)
    except ValidationFailedError as exc:
        print(exc.report, end="")
        sys.exit("error: epubcheck failed; the report is in " + str(path / REPORT_NAME))
    except (
        ExportError,
        EpubcheckNotFoundError,
        FontCoverageError,
        InlineCodeError,
        EpubError,
        OSError,
    ) as exc:
        sys.exit(f"error: {exc}")
    print(f"Exported: {out}\nepubcheck report: {path / REPORT_NAME}")


def _evaluate(
    args: argparse.Namespace,
    adapter: Adapter | None,
    embedder: Embedder,
    comet: CometScorer | None = None,
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
            comet=(comet or UvCometScorer()) if args.comet else None,
        )
    except (EvaluateError, EmbeddingsUnavailableError, CometError) as exc:
        sys.exit(f"error: {exc}")
    except CapReachedError as exc:
        sys.exit(f"stopped: {exc}")
    except InvalidOutputError as exc:
        sys.exit(_invalid_message(exc, path))
    except ModelRefusedError as exc:
        sys.exit(_refused_message(exc, path))
    if not json.loads(out.read_text())["evaluation_mode"]:
        print(
            "warning: this workspace was not initialised with `init --evaluation`, so"
            " established-terminology lookups may have used the web; scores may be inflated",
            file=sys.stderr,
        )
    print(f"Quality report: {out}\nReadable copy: {path / REPORT_MD}")


class _ProductionAdapter:
    """The pydantic-ai adapter, built on the first model call: a run that has nothing left for
    the model to do needs no key."""

    def __init__(self) -> None:
        self._adapter: Adapter | None = None

    def complete(self, request: LLMRequest, key: str, attempt: int) -> RawAnswer:
        if self._adapter is None:
            providers = sorted({model.split(":", 1)[0] for model in STAGE_MODELS.values()})
            missing = [PROVIDER_KEYS[p] for p in providers if not os.environ.get(PROVIDER_KEYS[p])]
            if missing:
                sys.exit(f"error: set {', '.join(missing)} in the environment to call the LLM")
            self._adapter = PydanticAIAdapter()
        return self._adapter.complete(request, key, attempt)


def _production_adapter() -> Adapter:
    return _ProductionAdapter()


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
    for stage, cost in est.by_stage.items():
        print(f"  {stage}: ${cost:.2f}")
    print(
        f"  one clean pass ${est.base_usd:.2f}"
        f" + {est.margin:.0%} margin for retries = ${est.cost_usd:.2f}"
    )
    if args.cap < est.cost_usd:
        print(
            f"Warning: the cap (${args.cap:.2f}) is below the estimate (${est.cost_usd:.2f});"
            " the run may stop before it finishes. Raise it with `run --cap`."
        )
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


def _approve(path: Path, choices: Path | None = None) -> None:
    if not (path / workspace.DB_NAME).is_file():
        sys.exit(f"error: not a workspace: {path}")
    try:
        approve_waiting_gate(path, choices)
    except (GateError, ReviewError) as exc:
        sys.exit(f"error: {exc}")
    print(f"Approved. Next: book-translator run {path}")
