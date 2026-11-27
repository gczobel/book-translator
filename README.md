# book-translator

Multi-pass literary book translator. EPUB in, translated EPUB out, an LLM doing the work a
professional translator does: macro analysis and style sheet, scene-level drafting, blind
cadence polish, fidelity gate, deterministic QA.

**Status:** pre-design. Research is done, the design interview (`/grill-with-docs`) has not
started. Read [`CONTEXT.md`](CONTEXT.md) first.

## Layout

- `docs/research/` — the two research reports behind the design
- `archive/` — raw Gemini chat dump and transcript the research came from
- `src/book_translator/` — package (Python 3.12, `uv`)

## Dev

```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
