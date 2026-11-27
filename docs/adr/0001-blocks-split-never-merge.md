# Source blocks are split, never merged or moved

Literary translators occasionally merge or split paragraphs. We allow only one of
the two: a source block becomes **one or more** target blocks in the same place and
order. Target blocks are never merged across source blocks, and text never moves
from one source block to another. Each target block records the source block it came
from. In-place rebuilding stays exact (each piece is a clone of the source element
with its class), every source block can still be checked against its translation
(omissions, length, tags), and resuming and side-by-side review stay per source block.
The model sees whole passages with context, never isolated blocks.

Splits exist for target-language conventions, chiefly Spanish dialogue. The English
source often carries several speech turns inline in one narrative paragraph. The
Spanish editorial norm (ePubLibre, and the published reference translations) gives
each speech turn its own raya paragraph. The style sheet setting `dialogue` selects
`raya-split` (the default: split when a block holds two or more speech turns) or
`inline-quotes` (keep one paragraph, use « »).

## Considered Options

- **Strict 1:1**: the simplest option, but it forces Spanish dialogue into an unnatural
  layout. The Canterville reference goes from 19 to 37 paragraphs in its chapter 1.
- **Free merge/split**: needs an alignment step and makes QA and rebuilding fuzzy.

## Consequences

- Alignment with a **reference translation** is a separate problem: published
  translations follow no such rule.
