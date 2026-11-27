# Open-Source Ecosystem & Institutional Standards Survey: Books, EPUBs & LLM Translation

> Compiled by the `Open-Source Ecosystem Researcher` sub-agent (`8b855c8e-afe7-4dce-bc5c-2824008a5c04`).

---

## 1. Existing Open-Source LLM Book / EPUB / Document Translators

### A. EPUB & General Book Translators
| Project | Repo / PyPI | Parsing & Tag Handling | Context / Coherence / Glossaries | LLM Backends | Where It Falls Short (Literary & Complex Non-Fiction) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`bilingual_book_maker`** (`yihong0618`) | [GitHub](https://github.com/yihong0618/bilingual_book_maker) / [`bbook-maker`](https://pypi.org/project/bbook-maker/) | Parses EPUB HTML/XHTML; defaults to `<p>` tags unless `--translate-tags` is set. Newer versions add **EPUB Plan Mode** (`--plan-classify`) using LLM classification + token-budget grouping + post-validation to preserve markup signatures. Also accepts TXT, MD, PDF, SRT. | `--use_context session` keeps an append-only rolling history (~1 chapter) with a handoff summary when token budgets fill; `--context_paragraph_limit`. No deep entity/character bible, coreference, or multi-pass literary critique. | OpenAI, Claude, DeepSeek, Gemini, local/custom via LiteLLM & API format flags. | Designed primarily for **bilingual side-by-side** output; paragraph-centric chunking loses cross-chapter voice/register consistency, lacks citation/footnote cross-linking awareness, and has no semantic front/body/backmatter taxonomy. |
| **`Ebook-Translator-Calibre-Plugin`** (`bookfere`) | [GitHub](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin) | Built on **Calibre's internal OEB/XHTML engine**, giving broad input/output format support (EPUB, MOBI, AZW3, PDF, DOCX) and paragraph-level block extraction. | SQLite/disk translation cache, regex/keyword exclusion rules, batch/advanced review modes. No native character tracking, dynamic glossary extraction, or narrative continuity across chapters. | OpenAI, Claude, DeepL, Google, custom engines. | Coupled to Calibre's embedded runtime/UI; flat paragraph-by-paragraph MT-style pipeline struggles with nested inline HTML/footnotes and lacks literary/scholarly multi-pass orchestration. |
| **`oomol-lab/epub-translator`** | [GitHub](https://github.com/oomol-lab/epub-translator) / [`epub-translator`](https://pypi.org/project/epub-translator/) | Python DOM traversal with explicit element classification (`is_inline_element()`, MathML `display` checks) separating block vs. inline tags cleanly while preserving images/CSS. | Custom prompts, local/cloud execution, MCP/OOMOL Studio integration; focused on bilingual or translated EPUB output. | OpenAI-compatible endpoints. | Lacks book-wide structural analysis, glossary extraction, character/speaker tracking, and back-translation/alignment QA. |
| **`KazKozDev/book-translator`** (*Tolmach*) | [GitHub](https://github.com/KazKozDev/book-translator) | Handles EPUB, PDF, DOCX, TXT; includes web UI with 3-panel side-by-side review. | Built-in glossary management for character/term consistency + self-reflection/refinement pass. | Local-first (**Ollama** / Ollama Cloud). | Local-model orientation & monolith UI; limited institutional EPUB3/footnote/citation semantics or automated QA alignment. |
| **`NeOzay/ebook-translator`** | [GitHub](https://github.com/NeOzay/ebook-translator) | Preserves EPUB structure, metadata, CSS, images; token-limit chunking with overlap. | **Multi-phase pipeline**: optional literary style analysis, glossary extraction, parallel translation, and two-stage **Pydantic** validation + LLM self-correction. | DeepSeek, OpenAI, OpenAI-compatible APIs. | Requires Python 3.14+/`uv`; relatively new/small community project; lacks NLP-backed coreference/entity extraction or embedding-based alignment QA. |
| **`NW15D/sunny-narrator`** | [GitHub](https://github.com/NW15D/sunny-narrator) | EPUB, PDF, FB2, TXT with checkpointing. | Glossary-driven + automated character name/gender extraction + dual-LLM (translate + proofread) QC loop. | Cloud/OpenAI-compatible LLMs. | Fiction/novel-oriented heuristics; not designed for scholarly/non-fiction citation graphs, complex tables, or W3C EPUB3/XLIFF standards. |
| **`hydropix/TranslateBooksWithLLMs`** | [GitHub](https://github.com/hydropix/TranslateBooksWithLLMs) | Chunked text extraction with formatting preservation & checkpoint resume across books/subtitles. | Basic chunking/resume; minimal literary/terminology modeling. | Ollama, OpenAI-compatible, Gemini, Mistral, DeepSeek, OpenRouter. | Wrapper/desktop app; lacks fine-grained DOM inline tag restoration and book-level taxonomy/QA. |
| **`neavo/LinguaGacha`** | [GitHub](https://github.com/neavo/LinguaGacha) | Multi-format (games/Ren'Py, subtitles, EPUB, PDF). | Terminology/glossary maintenance and batch LLM localization. | Multiple LLM backends. | Primarily geared toward game/VN scripts rather than deep book anatomy (TOC/footnotes/bibliographies). |
| **`al-nemirov/epub-translator`** | [GitHub](https://github.com/al-nemirov/epub-translator) | Unzips EPUBs, parses XHTML nodes, passes previous paragraphs as context. | Simple rolling paragraph context only. | OpenAI API. | Minimalist; no glossaries, structural taxonomy, or multi-pass refinement. |

### B. Layout-Preserving PDF Translators
- **`PDFMathTranslate`** (`pdf2zh` / `PDFMathTranslate-next`): [`pdf2zh-next`](https://pypi.org/project/pdf2zh-next/) / [GitHub](https://github.com/PDFMathTranslate/PDFMathTranslate-next)
- **`BabelDOC`** (`funstory-ai/BabelDOC`): [`BabelDOC`](https://pypi.org/project/BabelDOC/) / [GitHub](https://github.com/funstory-ai/BabelDOC)
- **Capabilities & Limits:** Built for **PDFs** (academic papers, technical books with math formulas, figures, multi-column layouts). BabelDOC uses Rust-accelerated parsing + layout models (`pdf2zh-next` integrates BabelDOC as a backend) to produce bilingual or translated PDFs with preserved typography. **Neither natively processes or outputs EPUBs** (their typesetting pipelines are coordinate-bound to PDF).

---

## 2. EPUB / PDF Parsing, Book Anatomy & Institutional Localization Standards

### A. Python Document & EPUB Parsing Comparison
| Tool / Library | Role & Strengths | Limitations / Caveats |
| :--- | :--- | :--- |
| **`EbookLib`** ([GitHub](https://github.com/aerkalov/ebooklib) / [PyPI](https://pypi.org/project/EbookLib/)) | **Best pure-Python EPUB container/spine/manifest manager.** v0.21 (Nov 2026) supports Python >=3.10–3.13+, dropped Python 2/`six`. Reads/writes ZIP, OPF metadata, NCX/NAV, spine order, images, CSS. | Treats XHTML `ITEM_DOCUMENT` content as opaque bytes/strings; naive re-serialization can strip `<head>` elements or break TOC/spine if misused. Must be paired with an XML/XHTML parser. |
| **`lxml`** (`lxml.etree` / `lxml.html`) | **Gold standard for EPUB XHTML DOM manipulation.** Full XML namespace support (`epub:type`, `xml:lang`, SVG/MathML), XPath, fast C (`libxml2`/`libxslt`), preserves `.text` and `.tail` nodes cleanly. | Requires careful handling of XHTML strictness and namespaces (`http://www.idpf.org/2007/ops`, `http://www.w3.org/1999/xhtml`). |
| **`zipfile` + `pydantic-xml`** ([PyPI](https://pypi.org/project/pydantic-xml/)) | Direct, zero-magic control over `META-INF/container.xml`, `.opf`, `nav.xhtml`, `toc.ncx` with strongly-typed Pydantic v2 XML models. | More boilerplate than `EbookLib` for writing/repackaging valid EPUBs. |
| **`beautifulsoup4`** (`bs4` w/ `lxml-xml`) | Ergonomic DOM API for messy EPUB2/HTML; handles `epub:type` queries via `lxml-xml` backend. | Slower than raw `lxml`; `html.parser` backend mangles XML namespaces. |
| **`selectolax`** (Lexbor C engine) | Fastest HTML5 parser for scraping plain text from clean HTML. | **Avoid for EPUB XHTML**: lacks XPath and proper XML/XHTML namespace support (`epub:type`, SVG, MathML). |
| **`epub-meta`** ([GitHub](https://github.com/paulocheque/epub-meta) / [PyPI](https://pypi.org/project/epub-meta/)) | Zero-dependency stdlib reader for EPUB 2/3 metadata. | Read-only, minimal utility; `EbookLib` or `lxml` supersedes it in a full pipeline. |
| **`calibre`** (`ebook-convert` / `calibre.ebooks.oeb`) | Industry-best format conversion (MOBI/AZW3/FB2/DOCX/RTF -> EPUB). | `calibre.ebooks.oeb` **cannot be `pip install`ed** (bundles its own Python + PyQt/C++ extensions; requires `calibre-debug -e`). Using `ebook-convert` via `subprocess` is disk-bound and coarse-grained. Use only as an **ingest normalizer** for legacy non-EPUB formats. |
| **`pypandoc`** ([PyPI](https://pypi.org/project/pypandoc/)) | Clean wrapper for Pandoc (Markdown/DOCX/LaTeX/HTML <-> EPUB). | Pandoc's AST flattens complex EPUB CSS/layout/custom `epub:type` semantics; great for Markdown/DOCX ingest, risky for round-tripping commercial EPUBs. |
| **PDF-to-Structured-Text:** **`Docling`** ([PyPI](https://pypi.org/project/docling/)), **`Marker`** ([PyPI](https://pypi.org/project/marker-pdf/)), **`MinerU`** ([GitHub](https://github.com/opendatalab/MinerU)), **`PyMuPDF4LLM`** ([PyPI](https://pypi.org/project/pymupdf4llm/)) | **Docling** (MIT, IBM): strong layout/reading order, tables, `DoclingDocument` tree, supports PDF + EPUB. **MinerU** (AGPL-3.0): top accuracy for academic PDFs, formulas (LaTeX), strips running headers/footers, isolates footnotes. **Marker** (GPL-3.0): PDF/EPUB/DOCX + optional `--use_llm`. **PyMuPDF4LLM** (AGPL/Commercial): fastest CPU scraping for simple born-digital PDFs. | PyMuPDF4LLM mixes up multi-column footnotes/marginalia. Docling/Marker/MinerU require 1–2GB+ ML models (GPU recommended for Marker/MinerU at book scale). |
| **EPUB Validation:** **`epubcheck`** ([PyPI](https://pypi.org/project/epubcheck/)), **Ace by DAISY** ([GitHub](https://github.com/daisy/ace)) | `epubcheck` (Python wrapper over W3C/DAISY Java validator) verifies OPF/XHTML/spine legality. **Ace** (`@daisy/ace` Node CLI) audits WCAG/EPUB Accessibility 1.1, heading hierarchy, reading order. | Require Java (`epubcheck`) / Node.js (`ace`) runtimes. Essential as post-build gates. |

### B. Institutional Standards for Book Anatomy & Localization Pipelines

#### 1. Book Anatomy & Structural Taxonomy Standards
Institutions classify books using a canonical **frontmatter / bodymatter / backmatter** partition plus typed divisions:
- **W3C EPUB 3 Structural Semantics (`epub:type`) & DPUB-ARIA (`role="doc-*"`):**
  - High-level partitions (`frontmatter`, `bodymatter`, `backmatter`) sit on `<body>` or wrapper `<section>` via `epub:type` (DPUB-ARIA intentionally has no role equivalents for these three).
  - Granular roles map cleanly between `epub:type` and `role="doc-*"`: `chapter` (`doc-chapter`), `part` (`doc-part`), `prologue`/`epilogue` (`doc-prologue`/`doc-epilogue`), `foreword`/`preface`/`introduction` (`doc-foreword`, `doc-preface`, `doc-introduction`), `epigraph` (`doc-epigraph`), `dedication` (`doc-dedication`), `toc` (`doc-toc`), `footnote` / `noteref` (`doc-footnote` / `doc-noteref`), `endnotes` (`doc-endnotes`), `bibliography` (`doc-bibliography`), `index` (`doc-index`), `appendix` (`doc-appendix`), `glossary` (`doc-glossary`), `colophon` (`doc-colophon`).
  - Navigation: EPUB 3 `nav.xhtml` (`properties="nav"` in OPF, `<nav epub:type="toc">` + `landmarks` + `page-list`) and legacy EPUB 2 `toc.ncx`.
- **XML Publishing Schemas (for Non-Fiction / Scholarly Books & Reference Taxonomies):**
  - **TEI P5** (Humanities): `<TEI><text><front> / <body> / <back>` with recursive `<div type="chapter|preface|bibliography|...">`.
  - **NISO/NLM BITS** (STM Books, JATS-derived): `<book>` with `<book-meta>`, `<book-front>`, `<book-body>` (recursive `<book-part book-part-type="chapter|part">`), `<book-back>` (`<ref-list>`, `<app-group>`).
  - **OASIS DocBook 5** (Technical Books): explicit semantic tags `<preface>`, `<chapter>`, `<appendix>`, `<glossary>`, `<bibliography>`, `<index>`.
- **Readium Web Publication Manifest (RWPM EPUB Profile):** ([`readium/go-toolkit`](https://github.com/readium/go-toolkit), `https://readium.org/webpub-manifest/profiles/epub`) — normalizes EPUB spine/nav into a clean JSON model (`readingOrder`, `resources`, `toc`, `landmarks`, `loa`/`loi`/`lot`/`lov`, `pageList`). Great blueprint for an internal Python `BookManifest` Pydantic schema.

#### 2. Institutional Translation & Localization Standards (Replacing Ad-Hoc Regex/DOM Scraping)
- **W3C ITS 2.0 (Internationalization Tag Set):** Defines declarative rules for what to translate and how tags behave: `its:translate="yes|no"` (e.g., skip `<code>`, `<kbd>`, ISBNs, bibliography keys, `epub:type="pagebreak"`), `its:withinText="yes|no|nested"` (distinguishes inline tags like `<em>`/`<sup>`/`<a epub:type="noteref">` from nested footnotes/subflows), `its:term` (glossary anchors), and `its:locNote` (translator context).
- **OASIS XLIFF 2.0 / 2.1:** Separates translatable text from raw HTML markup via `<originalData>` and inline placeholders (`<pc>` paired codes like `<em>...</em>`, `<ph>` standalone tags like `<br/>`, `<sc>`/`<ec>` for overlapping tags). **Key insight for LLMs:** Instead of exposing raw `<a class="calibre12" href="../Text/notes.xhtml#fn4">` to an LLM (which invites attribute hallucination), serialize inline nodes into compact indexed markers (e.g. `<pc id="1">...</pc>` or `[[1]]...[[/1]]`) backed by an `originalData` map, validate marker balance/nesting with Pydantic/XML parser after LLM output, and rehydrate back into the `lxml` DOM.
- **SRX (Segmentation Rules eXchange), TMX, TBX:** Standard XML formats for sentence segmentation rules, Translation Memory exchange, and TermBase/glossary exchange.
- **Tooling:**
  - **Okapi Framework (`tikal` CLI / Longhorn REST):** ([okapiframework.org](https://okapiframework.org/)) Java-based industry gold standard with native `okf_epub` and `okf_html5-its` filters, SRX segmentation, and XLIFF 1.2/2.0 round-tripping. Can be driven via `subprocess` (`tikal -x` / `tikal -m`) or REST if you want zero custom filter code, though Java runtime + XLIFF-to-LLM batching adds glue.
  - **Python-native equivalents:** **`translate-toolkit`** ([GitHub](https://github.com/translate/translate) / [PyPI](https://pypi.org/project/translate-toolkit/)) supports XLIFF 1.2/2.0, TMX, TBX, and `pofilter` QA checks (actively maintained by Weblate); **`itstool`** (Python W3C ITS -> PO); **`choppa-srx`** (`pip install choppa-srx`, pure-Python SRX segmenter bundling LanguageTool rules).

---

## 3. Book-Scale NLP, Taxonomy, Citations & QA / Alignment Libraries

### A. Literary / Fiction NLP vs. General & Non-Fiction Analysis
| Library | PyPI / GitHub | Capabilities | Python 3.10–3.12 Status & Caveats |
| :--- | :--- | :--- | :--- |
| **`BookNLP`** | [GitHub](https://github.com/booknlp/booknlp) / [PyPI](https://pypi.org/project/booknlp/) | End-to-end **English fiction** pipeline: character name clustering (e.g., *Mr. Darcy* = *Fitzwilliam* = *he*), quote/speaker attribution, coreference, supersense & event tagging, gender inference. | **Major Maintenance Caveat:** Designed for Python 3.7 and older `transformers`/`torch` pins; minimal maintenance. Installing on Python 3.11/3.12 causes dependency conflicts unless patched or isolated in a separate microservice/venv. Also **English-only**. |
| **`spaCy`** (v3.8) | [PyPI](https://pypi.org/project/spacy/) | Fast multilingual tokenization, POS, dependency parsing, NER, sentence segmentation across 25+ languages. | **Fully compatible with Python 3.10–3.12 & Pydantic v2** (note: v3.8 does **not** officially support Python 3.13 yet). |
| **`GLiNER`** | [PyPI](https://pypi.org/project/gliner/) | Lightweight zero-shot NER for **arbitrary entity labels** (characters, locations, organizations, technical concepts, historical figures, titles) in fiction *and* non-fiction. | Actively maintained; works on Python 3.10–3.12 with modern `torch`/`transformers`. Strong replacement for rigid NER when combined with LLM entity consolidation. |
| **`fastcoref`** | [GitHub](https://github.com/shon-otmazgin/fastcoref) / [PyPI](https://pypi.org/project/fastcoref/) | Fast coreference resolution (`F-COREF` / `LingMess`) with spaCy component integration. | Moderate maintenance; works on Python 3.10–3.11 cleanly; Python 3.12 can hit wheel/dependency friction depending on `torch`/`transformers` pins. |
| **`pySBD`** | [PyPI](https://pypi.org/project/pysbd/) | Rule-based sentence boundary disambiguation across 20+ languages (handles abbreviations, decimals, initials). | Pure Python, lightweight, works on Python 3.10–3.12+. |
| **`textstat`** | [PyPI](https://pypi.org/project/textstat/) | Readability/complexity metrics (Flesch-Kincaid, SMOG, etc.) useful for register/style profiling & drift checks. | Actively maintained, pure Python, 3.10–3.12+. |
| **Non-Fiction Citation & Bibliography Parsers:** `grobid-client-python` + `grobid_tei_xml`, `bibtexparser`, `anystyle` | [GROBID](https://github.com/kermitt2/grobid) / [Client](https://pypi.org/project/grobid-client-python/) / [`bibtexparser`](https://pypi.org/project/bibtexparser/) | **GROBID** (Docker/Java + Python client) extracts scholarly PDFs/references into TEI-XML + Crossref consolidation. **AnyStyle** (Ruby CLI) parses messy Chicago/APA/MLA humanities & non-fiction bibliographies into CSL-JSON/BibTeX. **`bibtexparser`** (v2.x, pure Python) parses/normalizes `.bib`. | Note: GROBID is biased toward STM articles; AnyStyle is more flexible on humanities/non-fiction book bibliographies. |

### B. Bilingual Alignment & Translation QA
| Library | Repo / PyPI | Capabilities & Role | Compatibility / Caveats |
| :--- | :--- | :--- | :--- |
| **`sentence-transformers` + `LaBSE`** | [PyPI](https://pypi.org/project/sentence-transformers/) / [LaBSE](https://huggingface.co/sentence-transformers/LaBSE) | 109-language cross-lingual sentence embeddings. Ideal for **translation completeness / omission / hallucination QA** (cosine similarity between aligned source & translated paragraphs/sentences). | Actively maintained, Python 3.10–3.12+. |
| **`Bertalign`** (`bfsujason/bertalign`) | [GitHub](https://github.com/bfsujason/bertalign) | 2-step embedding + DP aligner built specifically for **literary books** (handles 1-to-many, many-to-1, many-to-many splits/merges). | Research repo (not actively maintained on PyPI; install from GitHub/fork). Sensitive to `torch`/`sentence-transformers` versions; works on 3.10–3.11. |
| **`Vecalign`** (`thompsonb/vecalign`) | [GitHub](https://github.com/thompsonb/vecalign) | Linear-time approximate DP sentence aligner using multilingual embeddings (LaBSE/LASER). | Install from GitHub; fast and language-agnostic; great for verifying sentence alignment at chapter scale. |
| **`translate-toolkit`** | [GitHub](https://github.com/translate/translate) / [PyPI](https://pypi.org/project/translate-toolkit/) | TMX/TBX/XLIFF generation + `pofilter` deterministic QA checks (untranslated strings, numbers, punctuation, placeholder/tag mismatch, length ratios). | Actively maintained (Weblate), Python 3.10–3.12+. |
| **`rapidfuzz`** | [GitHub](https://github.com/rapidfuzz/RapidFuzz) / [PyPI](https://pypi.org/project/rapidfuzz/) | MIT-licensed C++ fuzzy string matching; fast glossary term verification, untranslated-span detection, and entity name matching. | Actively maintained, Python 3.10–3.13+. |

---

## 4. LLM Orchestration, Caching & Pragmatic "Buy/Reuse vs. Build" Stack

### Orchestration & Structured Output Options
- **Lightweight Core (`pydantic` v2 + `litellm` / `google-genai` / `openai` + `instructor` + `tenacity`):**
  - `litellm` ([PyPI](https://pypi.org/project/litellm/)) gives provider-agnostic routing (Gemini, Claude, OpenAI, DeepSeek, Ollama) + cost/token tracking; `google-genai` ([PyPI](https://pypi.org/project/google-genai/)) gives native Gemini context caching & structured outputs.
  - `instructor` ([PyPI](https://pypi.org/project/instructor/)) enforces strict Pydantic schemas with automatic validation-error retry loops (e.g., guaranteeing valid glossary entries, entity records, and balanced inline tag placeholders).
- **Heavy Graph Frameworks (`langgraph`):** ([PyPI](https://pypi.org/project/langgraph/)) Useful *if* you need durable visual state machines/human-in-the-loop interrupts, but adds abstraction weight over what is fundamentally a deterministic, resumable batch DAG (Parse -> Analyze -> Translate -> Critique -> QA -> Reassemble).
- **Caching & Checkpointing (`diskcache` / SQLite):** `diskcache` ([PyPI](https://pypi.org/project/diskcache/)) or a thin SQLite state store keyed by `(book_hash, segment_id, model, prompt_hash, glossary_hash)` handles crash recovery, partial re-runs, and prompt-iteration cost control cleanly.

### Recommended "Buy/Reuse vs. Build" Architecture (Python 3.12)

**Adopt Off the Shelf (Reuse):**
1. **EPUB Container & Validation:** `EbookLib` (0.21+) for ZIP/OPF/spine/asset packaging + `lxml` (`etree`/`html`) for namespace-aware XHTML DOM manipulation + `epubcheck` (post-build gate) + Calibre `ebook-convert` *only* as an optional pre-ingest converter for MOBI/AZW3/FB2.
2. **PDF Ingest (General Books):** `Docling` (MIT, general non-fiction/tables/reading order) with `MinerU` as an optional GPU heavy-hitter for STEM/equation/footnote-dense PDFs.
3. **Segmentation & Alignment/QA:** `pySBD` (or `choppa-srx`) for sentence boundaries; `translate-toolkit` for TBX/TMX/XLIFF export & deterministic QA checks; `rapidfuzz` + `sentence-transformers` (`LaBSE`, optional `vecalign`/`bertalign`) for semantic omission/hallucination checks.
4. **NLP Signals (Optional Pre-Pass):** `spaCy` (3.8) + `GLiNER` for fast multilingual entity extraction; treat `BookNLP` only as an isolated optional English-fiction sidecar due to its stale Python/PyTorch pins (prefer LLM-assisted chapter entity/speaker profiling on 3.12).
5. **LLM Plumbing:** `pydantic` v2 + `litellm` (or native `google-genai`) + `instructor` + `diskcache`/SQLite.

**Build Thin Custom Layer (Our Core Differentiator):**
1. **Standards-Aligned Book IR & Taxonomy Classifier:** A Pydantic `BookDocument` model inspired by **RWPM** + **EPUB 3 `epub:type` / DPUB-ARIA** (`frontmatter`/`bodymatter`/`backmatter`, `chapter`, `footnote`/`noteref`, `bibliography`, `index`, `epigraph`) that classifies sections and assigns **W3C ITS 2.0-style rules** (`translate=yes|no`, `withinText`, `locNote`).
2. **XLIFF-Inspired Inline Tag Codec (`lxml` <-> LLM):** Converts XHTML blocks into clean text with compact paired/standalone markers (`<pc id="1">...</pc>`, `<ph id="2"/>`) + `originalData` lookup, verifies tag preservation via Pydantic/XML validation after LLM output, and surgically re-injects into `lxml` DOM nodes (preserving links, footnote `href`s, `<em>`, `<sup>`, Ruby/MathML).
3. **Book-Level Memory & Multi-Pass Pipeline:**
   - *Pass 1 (Book Bible):* Style/register profile + dynamic glossary/character/terminology table (entities, gender/pronouns, honorifics, domain terms, citation conventions) + chapter summaries.
   - *Pass 2 (Context-Aware Translation):* Batch segments with sliding context window + relevant glossary/entity slice + linked footnote context.
   - *Pass 3 (Literary/Editorial Critique & QA):* Deterministic checks (tag balance, untranslated spans, numbers, `LaBSE` similarity threshold) + targeted LLM revision pass on flagged segments only.
