# Existing translations never feed the draft

No stage reads the text of an existing translation of the book being translated. Doing so
would copy another translator's work, and for test books it would contaminate the comparison
with the reference translation. Two narrow exceptions are allowed, and both are switched off
for evaluation runs:

- **Established terminology**: S1's web research may take terms a published series already
  uses in the target language (names, invented words). They come from wikis or earlier
  volumes, never from the book's own translated text. Each is stored as a glossary entry
  marked "established", with its source.
- **Reference translations**: used only after the build, by the scoring step (alignment, chrF,
  LLM judge, optional COMET).

A sister-language translation as evidence for the address grid is a possible later
extension (issue #3). It would only feed the analysis, never the drafter.
