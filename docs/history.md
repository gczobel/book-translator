# How the project started

## The problem

The goal is to translate whole fiction books (the first target was a ~150k-word EPUB) with a
professional literary translator's quality and long-range consistency: names, forms of
address, recurring motifs and voice have to hold across hundreds of pages.

The obvious tool, the Calibre plugin `bookfere/Ebook-Translator-Calibre-Plugin`, was analysed
first and ruled out as a base. Every request is stateless and covers a single paragraph. The
glossary swaps terms for opaque `{{id_n}}` tokens instead of informing the model. Merging is
chapter-blind and splits on `\n\n`. The cache holds a single translation column, and the
code depends on Calibre's runtime. None of the other open-source book translators surveyed
combines book structure with a multi-pass literary workflow either (see
`docs/research/ecosystem_and_standards.md`).

## Phase 1: research (Gemini, 2026-11)

A first conversation in Gemini's Antigravity CLI produced the two reports in
`docs/research/`:

- `translator_craft_and_pipeline.md`: how professional literary translators work, mapped to
  a stateful 8-stage LLM pipeline (S1 analysis → S8 QA and build).
- `ecosystem_and_standards.md`: the existing OSS tools, Python EPUB/NLP/alignment libraries,
  and the EPUB 3, ITS 2.0 and XLIFF standards.

It also settled the early shape: fiction first, a standalone Python CLI, a real multi-provider
API driver, and human review after the analysis. The session ran out of quota, and the
work moved to Claude Code. The raw chat is not kept. These reports are its lasting output.

## Phase 2: design interview (Claude Code, 2026-11-27)

A `/grill-with-docs` session turned the research into decisions:

- Vocabulary: `GLOSSARY.md`.
- Hard-to-reverse choices: `docs/adr/` (block splitting, in-place EPUB rebuild, LLM access
  behind our own interface, existing translations never feeding the draft).
- ePubLibre's production standards and Spanish typography, condensed for agents:
  `docs/reference/epublibre.md`.
- Test books: *The Canterville Ghost* (small) and *The Great Gatsby* (main), as ePubLibre
  English/Spanish pairs kept outside git.
- Deferred ideas: GitHub issues labelled `enhancement`.

The repository was made public at this point, without the raw research chat, so that the
maintenance automation (Dependabot, rulesets, code and secret scanning) is available for free.
