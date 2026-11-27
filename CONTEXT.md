# Handoff: starting the book-translator design

Written 2026-11-27 to move a conversation from Gemini (Antigravity CLI, quota exhausted) to
Claude Code. The raw conversation is in `archive/` (`gemini_chat_dump.txt`,
`transcript_full.jsonl`). Do not re-read it unless something below is unclear; the research
reports in `docs/research/` hold the substance:

- `docs/research/translator_craft_and_pipeline.md` — how professional literary translators
  work, mapped to a stateful LLM pipeline (stages S1–S8, schemas, QA gates, failure modes).
- `docs/research/ecosystem_and_standards.md` — existing OSS book translators, Python
  EPUB/NLP/alignment libraries, EPUB 3 / ITS 2.0 / XLIFF standards, a Reuse-vs-Build stack.

## Goal

A tool that translates a whole book (first target: a ~150k-word, 857k-char fiction EPUB) with
professional-translator quality and long-range coherence, as a deterministic, resumable
process with the LLM doing the human work. Must scale down (novella) and up (500k words).

## Why not the existing tools

The Calibre plugin `bookfere/Ebook-Translator-Calibre-Plugin` (cloned at
`~/development/Ebook-Translator-Calibre-Plugin`) was analysed: every request is stateless and
single-paragraph; no cross-request context, no glossary-aware prompting (glossary swaps terms
for opaque `{{id_n}}` tokens), merging is chapter-blind and splits on fragile `\n\n`, the
cache schema is a flat single `translation` column, and the code imports `calibre.*`. No
surveyed OSS tool combines standards-based book taxonomy with the full literary workflow.

## Decisions made (with the user)

- **Scope v1:** fiction. Non-fiction (canonical-quote lookup, citations, index rebuild,
  PDF via Docling) comes later as optional hooks.
- **Shape:** standalone Python package/CLI, Calibre-free. Python 3.12, `uv`.
- **Calibre plugin:** the user prefers contributing to it where possible but does not want
  its architecture to limit the design. Plan: optional bridge via its SQLite cache, and
  possible upstream PRs (chapter-aware merge, native Gemini `systemInstruction`, rolling
  context hook). Not a v1 dependency.
- **LLM access:** a real API driver, multi-provider (litellm or a thin adapter), comparable
  in breadth to the plugin's engines. The "offline prompt-pack for the web chat" idea was
  dropped. The user's Google AI Plus plan gives no API access, so a key/billing is needed.
- **Stack leaning (from research, not yet locked):** EbookLib + lxml (+ epubcheck gate),
  Pydantic v2, litellm + instructor, SQLite/diskcache for state, pySBD, translate-toolkit,
  rapidfuzz, LaBSE for QA. Book IR modelled on EPUB 3 `epub:type` / DPUB-ARIA / RWPM;
  W3C ITS 2.0 rules for translate-or-not; XLIFF-style `<pc>`/`<ph>` inline tag codec with an
  `originalData` map instead of `{{id}}` placeholders.
- **Pipeline (from research):** S1 macro analysis (style sheet, character/voice cards,
  dyadic register edges, glossary, motifs) → S2 research enrichment → S3 hot draft with
  `[TK]` tags → S4 TK resolution/propagation → S5 comparative fidelity → S6 blind cadence
  polish (source withheld) → S7 post-polish fidelity gate → S8 deterministic QA + compile.
- **Human-in-the-loop:** yes, a review gate after S1 (style sheet/glossary) and for S4 TKs.
- **First milestones:** an Architecture & Schema Blueprint first; a Stage 1 prototype (EPUB →
  Book IR → XLIFF-style codec → round-trip → epubcheck on a real fiction EPUB) "in a while".

## Open questions (ask the user)

1. **Source and target language** of the test book and the tool. Never stated.
2. **API provider/key** to develop against (AI Studio free tier? Claude? other?) and a
   per-book cost budget.
3. Issue tracker for the Matt Pocock skills: local `.scratch/` markdown or GitHub Issues
   (`setup-matt-pocock-skills` asks).
4. Which real EPUB to use as the prototype fixture (books are gitignored; keep it outside
   the repo or in `.work/`).

## Repo state

- GitHub: private `gczobel/book-translator`, `main` holds only the initial README.
- Branch `chore/project-scaffold`: uv project, ruff + pytest, CI workflow, research docs,
  archive, this file. Open PR for it; keep pushing later work to feature branches.
- User git rules: feature branches for non-trivial work, atomic Conventional Commits, PR
  opened early, review fixes in their own commits.

## Suggested next steps / skills

1. Run `/setup-matt-pocock-skills` once (tracker, labels, doc paths).
2. Run `/grill-with-docs` (preferred over `/wayfinder` for v1): answer the open questions,
   create `GLOSSARY.md` (lock terms: book, chapter, scene, segment, paragraph, inline tag,
   motif, style sheet, voice card) and ADRs for the hard-to-reverse choices above.
3. If EPUB round-tripping stays uncertain, `/prototype` it on a throwaway branch.
4. Then `/to-spec` → `/to-tickets` (tracer-bullet slices) → `/implement` with `/tdd` and
   `/code-review`. Use `/handoff` at phase boundaries.
