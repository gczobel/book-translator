# book-translator

Multi-pass literary book translator. EPUB in, translated EPUB out, an LLM doing the work a
professional translator does: macro analysis and style sheet, scene-level drafting, blind
cadence polish, fidelity gate, deterministic QA.

**Status:** design. Decisions are recorded, and no pipeline code exists yet. Start with
[`docs/history.md`](docs/history.md), [`GLOSSARY.md`](GLOSSARY.md) and [`docs/adr/`](docs/adr/).

## Layout

- `docs/history.md`: how the project started
- `docs/research/`: the two research reports behind the design
- `docs/reference/`: condensed external standards (ePubLibre)
- `docs/adr/`, `GLOSSARY.md`: decisions and vocabulary
- `src/book_translator/` — package (Python 3.12, `uv`)

## Dev

```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
