# Book Translator

Translates whole fiction books from one language to another with the working
method of a professional literary translator: a whole-book analysis first, then
several drafting and revision passes.

## Language

### The book and its structure

**Book**:
One work being translated, received as a single EPUB in the source language.
_Avoid_: ebook, document, file

**Source** / **Target**:
The language and text the book is translated from / into.
_Avoid_: original/translation (when referring to languages), input/output

**Chapter**:
A logical division of the book's body as the author made it, found from the
table of contents and headings. It is not tied to the files that hold it.
_Avoid_: section, file, spine item

**Scene**:
A continuous run of text inside a chapter, bounded by scene breaks or by the
chapter's start and end.
_Avoid_: section, part

**Scene break**:
A structural marker between scenes (blank space, asterism, ornament). It is
preserved, never translated.
_Avoid_: separator, divider

**Block**:
One paragraph-level unit of text: a paragraph, heading, verse line group or
list item. Each source block becomes one or more target blocks, never merged
with another.
_Avoid_: segment, paragraph (when the unit is meant generically), node

**Passage**:
A run of consecutive blocks within one scene that is translated together in one
request, with surrounding text given as read-only context.
_Avoid_: chunk, batch, segment

**Front matter** / **Back matter**:
The parts of the book before and after the chapters (cover, synopsis, title page,
credits page, dedication / about the author, notes). Each is translated, rewritten
or kept as-is according to its kind.
_Avoid_: extras, boilerplate

**Credits page**:
The front-matter page that names the original title, the source edition and who
translated the book. In our output it states that the translation is machine-assisted.
_Avoid_: info page, colophon

### Translation decisions

**Book bible**:
Everything known about the book before drafting: its profile, style sheet, cast,
address grid, glossary, motifs and chapter summaries.
_Avoid_: project bible, metadata, context

**Style sheet**:
The book's typography and house-style choices for the target text (dialogue
layout, quotation marks, how thoughts, numbers and titles are written).
_Avoid_: style guide, CSS (a different thing)

**Voice card**:
A character's way of speaking: register, verbal tics, words they would never use,
sample lines.
_Avoid_: persona, character profile

**Address grid**:
For each directed pair of characters, which form of address the speaker uses
(e.g. tú or usted) and where in the book it changes.
_Avoid_: formality matrix, T-V table

**Motif**:
A recurring image or phrase the author repeats deliberately, rendered identically
every time it appears.
_Avoid_: theme, leitmotif, keyword

**TK**:
A spot the drafter could not settle confidently, recorded with candidates and a
provisional rendering instead of a guess. A book can't be built while a TK is open.
_Avoid_: placeholder, todo, flag

**Review gate**:
A point where the pipeline stops for the human to look at its decisions. The
analysis gate can be skipped. The TK gate always stops.
_Avoid_: checkpoint, approval step

### Reference material

**Reference translation**:
An existing published translation of a test book, used only to judge the
quality of our output, never as input to translating it.
_Avoid_: gold standard, ground truth
