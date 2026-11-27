# Rebuild the source EPUB in place

The translated book is produced by copying the source EPUB and replacing the text
inside its existing XHTML. We don't regenerate an EPUB from our internal model,
because regenerating would lose the publisher's markup, classes, CSS and file layout.
Keeping them is the surest way to pass epubcheck and to keep the book looking like
the original. "In place" is not "text only", though: the tool applies a fixed, tested
set of synchronized edits alongside the text:

- Chapter titles in headings and `title` attributes are kept equal to `toc.ncx` / nav
  labels and the TOC page.
- OPF metadata is updated: `dc:title`, `dc:description`, `dc:language`, and the
  translator credit (`dc:contributor` role `trl`).
- `xml:lang` is set to the target language on every content document.
- The credits page records the original title, the source edition and the machine-assisted
  translation (tool, model, date). Source branding (e.g. the ePubLibre logo and ex
  libris) is removed so the output never passes itself off as a release of that group.
- Notes are renumbered when translator's notes are added.

Embedded fonts are checked for target-language glyph coverage, and a gap fails the
build loudly. Splitting oversized files is deferred until a real book needs it.

## Considered Options

- **Regenerate from the internal model**: a cleaner pipeline, but it discards the source's
  styling and invites structural regressions on every book.
- **Full ePubLibre template conformance**: renames files and adds template pages. That
  amounts to regenerating, and the output must not pose as an ePubLibre release anyway.
