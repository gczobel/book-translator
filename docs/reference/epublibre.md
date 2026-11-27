# ePubLibre (Proyecto Scriptorium) reference for agents

Condensed from the official manuals in `docs/epublibre/`:

| Short cite | Source |
|---|---|
| **Base** | *ePub base ePL* r2.1 (the template). Files cited as `Base/<file>` |
| **I** | *Aprende a maquetar I: Manual básico* r3.1 |
| **II** | *Aprende a maquetar II: Herramientas útiles* r3.0 |
| **III** | *Aprende a maquetar III: Código avanzado* r3.0 |
| **IV** | *Aprende a maquetar IV: Imágenes y gráficos svg* r3.0 (GIMP and SVG; mostly irrelevant here) |

The manuals have no printed section numbers. `§` numbers below come from the manuals' XHTML file names (e.g. `3.2.3.notas.xhtml` → I §3.2.3). Manual II Part 5 files are unnumbered, so they are cited by topic (II §5 *Comillas*). **(?)** marks an inference or a point the manuals leave open. Spanish terms and class names are given verbatim.

Ground rules that apply throughout:
- ePubLibre books are **EPUB 2.0** (OPF `version="2.0"`, `toc.ncx`, XHTML 1.1 doctype, no `nav.xhtml`).
- The manuals target Spanish books. Their typography follows the RAE (2010 orthography). II §5.1 says the rules are *orientativas*; consistency within a book is what matters.
- Only `epl.css` and the fixed pages are standardised. **Most content classes (poems, letters, subtitles, drop caps) are the editor's own choice** and differ from book to book. Detect structure by tag and position first, and by class name second.

---

## 1. Template anatomy (ePub base r2.1)

### 1.1 Files and spine order

| Spine # | File (`OEBPS/Text/`) | Required | Stylesheets linked | Content / notes |
|---|---|---|---|---|
| 1 | `cubierta.xhtml` | yes, **do not modify** | epl.css | `<body class="sinmargen">`, `<h1 class="oculto" title="Cubierta"></h1>`, `<div class="cubierta"><svg viewBox="0 0 600 900" …><image xlink:href="../Images/cover.jpg" width="600" height="900"/></svg></div>`. The viewBox must match the real size of cover.jpg |
| 2 | `sinopsis.xhtml` | yes | epl.css | `<div class="sinopsis"><p>…</p></div>`. Text must equal `dc:description` (I §3.1.4) |
| 3 | `titulo.xhtml` | yes | epl.css | `div.tlogo` (EPL_logo.png), `p.tautor`, `h1.ttitulo`, `p.tsubtitulo`, `p.tserie` ("Saga: Serie Volumen"), `p.trevision` ("ePub r1.0"), `p.tfirma` (editor alias + `<span class="tfecha">dd.mm.yy</span>`). No images or fonts allowed; use a separate *portadilla* after info (I §3.1.4) |
| 4 | `info.xhtml` | yes | epl.css | Credits, see §1.3 |
| 5 | `TOC.xhtml` | optional | sgc-toc.css only | HTML TOC. Required only if headings go down to `<h3>` or lower (required in ePub3). It may instead go at the end of the book (I §3.1.4) |
| 6 | `dedicatoria.xhtml` | optional | epl + style | `<div class="dedicatoria"><p>…</p></div>`, no heading. Only for the original book's dedication |
| 7… | `Section0001.xhtml`… | yes | epl + style | Body text, **one chapter per file**, each ≤ 300 KB (I §3.2.1). Files may be renamed (`cap1`, `c01`), with no spaces, accents or odd characters |
| n‑1 | `autor.xhtml` | optional | epl.css | `<h1 title="Sobre el autor" class="oculto"></h1>`, `<p class="vineta"><img id="iautor" alt="Foto del autor" src="../Images/autor.jpg"/></p>`, `<div class="autor"><p>NOMBRE DEL AUTOR (lugar, año - …). …</p></div>`. The bio starts with the name IN CAPITALS (I §3.1.4) |
| n | `notas.xhtml` | optional | epl + style | `<h1>Notas</h1>` + `div.nota` blocks (§2.4). It may be split into several files, with the heading only in the first (Base comment) |

- ePLValidator enforces this order. ERROR 75: the first four fixed sections must be in order. ERROR 76: `autor` then `notas` must be the **last two** files (I §3.4.5).
- There is **no `epigrafe.xhtml` in base r2.1**. The template's epigraph sits at the top of `Section0001.xhtml` (§2.5). Separate epigraph or *portadilla* files are editor-made **(?)**.
- Other files: `Styles/{epl,style,sgc-toc}.css`, `Images/{cover.jpg, autor.jpg, EPL_logo.png, ex_libris.png, asterisco3.png, comilla1.png, fuente.png}`, `META-INF/com.apple.ibooks.display-options.xml` (`specified-fonts=true`, mandatory since base r1.1, ERROR 73/74), `toc.ncx`, and optionally `Fonts/`. Unused images are deleted (I §3.1.1).
- Every content XHTML: `<html xmlns=… xml:lang="es">`, a `<title>` (recommended), **`epl.css` linked first**, then `style.css` (I §3.2.1; validator "La hoja de estilos %s debe ser la primera…"). No XHTML may be empty or contain only hidden content, because some readers crash (I §3.2.1).
- OPF `<guide>`: cover→cubierta, text→sinopsis, title-page→titulo, copyright-page→info, dedication, notes, toc.

### 1.2 OPF metadata conventions (Base `content.opf`, I §3.1.2)

```xml
<dc:title>Título</dc:title>                                   <!-- same as titulo.xhtml h1 and ncx docTitle (ERROR 08/27) -->
<dc:creator opf:role="aut" opf:file-as="Apellidos, Nombres">Nombres Apellidos</dc:creator>
<dc:language>es</dc:language>
<dc:contributor opf:role="trl" opf:file-as="Apellidos, Nombres">Nombres Apellidos</dc:contributor> <!-- mandatory for translations -->
<dc:subject>Novela, Otros</dc:subject>                       <!-- Género, Subgénero(s): fixed Spanish list, no Tipo -->
<dc:description>Sinopsis</dc:description>                    <!-- = sinopsis.xhtml, tags stripped, italics → « » -->
<dc:date opf:event="publication">2018-04-23</dc:date>        <!-- FIRST publication in ORIGINAL language -->
<dc:publisher>ePubLibre</dc:publisher>                       <!-- exactly this (ERROR 07) -->
<dc:identifier opf:scheme="EPL">00000</dc:identifier>        <!-- web EPL_id -->
<dc:identifier opf:scheme="revision">1.0</dc:identifier>
<meta content="Serie" name="calibre:series" /><meta content="1" name="calibre:series_index" />
<dc:date opf:event="modification">2019-03-06</dc:date>
<dc:identifier id="BookId" opf:scheme="UUID">urn:uuid:…</dc:identifier>   <!-- must differ from base's all-zeros -->
<meta name="cover" content="cover.jpg" />
```
- `file-as` is mandatory for every person and follows BNE practice. Particles go with the given name: `Cervantes Saavedra, Miguel de`. Initials go with the given name: `Martin, George R. R.`. Several people are joined with ` & `. 3+ authors → `AA. VV.`. Unknown translator → `Desconocido` (≠ `Anónimo`).
- Genres are 1 genre + 1–5 subgenres, spelled exactly as in I §3.1.5. Fiction genres: Guion, Novela, Poesía, Publicaciones periódicas, Relato, Teatro. Fiction subgenres: Aventuras, Bélico, Ciencia ficción, Didáctico, Drama, Erótico, Fantástico, Filosófico, Histórico, Humor, Infantil, Interactivo, Intriga, Juvenil, Policial, Psicológico, Realista, Romántico, Sátira, Terror, Otros. They stay in Spanish even for books in other languages.
- Any OPF change must be followed by regenerating the TOC, so that the UUID and title get copied into `toc.ncx` (ERROR 13). Never hand-edit `toc.ncx` (I §3.1.1, §3.2.4).
- Cross-file consistency checked by ePLValidator (I §3.4.5): title, author, translator, series and volume, revision, editor alias, original publication year (OPF ↔ info), modification date (OPF ↔ titulo).

### 1.3 `info.xhtml` (credits page, Base + I §3.1.4)

```html
<div class="info">
  <p>Título original: <cite>Original Title</cite></p>      <!-- in the ORIGINAL language, its own orthography -->
  <p>Autor, año de 1.ª publicación en idioma original</p>   <!-- e.g. "Erle Stanley Gardner, 1935" -->
  <p>Traducción: Traductor</p>                             <!-- delete if not translated; "Desconocido" if unknown -->
  <p>Ilustraciones: Ilustrador</p>
  <p>Diseño/Retoque de cubierta: Diseñador</p>             <!-- "Diseño" = new cover, "Retoque" = adapted -->
  <p>&nbsp;</p>
  <p>Editor digital: Titivillus</p>                        <!-- alias; Titivillus = anonymous -->
  <!-- Primer editor: X (r1.0 a 1.x) / Segundo editor: Y (r2.0 a 2.x) / Corrección de erratas: … -->
  <p>ePub base r2.1</p>                                    <!-- TEMPLATE version, NOT the book revision -->
  <p><img alt="Fuente incrustada" src="../Images/fuente.png" class="icono_fuente"/></p>  <!-- only if fonts embedded -->
</div>
<div class="bloque_exlibris"><img src="../Images/ex_libris.png" class="ancho_full" alt="Ex libris"/></div>
```
- Unused lines are deleted. Comments may be deleted. Older bases put the alias in `<p class="salto10">Editor digital: …</p>` (I §3.1.4).
- The book revision lives in `titulo.xhtml` (`ePub r1.0`), in the OPF `revision` identifier and in the file name. Rules (I §3.3.5): start at r1.0, then +0.1 per update, with one decimal only (r1.9 → r2.0). A big change may jump to the next integer. An alternative non-standard edition (xhtml > 300 KB, non-ePub2 tags) gets an `a` suffix: r1.0a. Candidate drafts use r0.1, r0.2….
- File name (I §4.1): `Apellido(s), Nombre(s) - [Serie Número] Título [EPL_ID] (r1.0 Editor)`. No accents, ñ or non-Latin characters. Allowed punctuation is `, . - _ ( ) &`. Titles use *mayúsculas normalizadas* (only the first word and proper nouns capitalised). Books not in Spanish append ` [EN]` etc. (ISO 639‑1).

### 1.4 Navigation
- `toc.ncx` `navPoint`s are generated by Sigil from the `<h1>…<h6>` headings. A heading's `title="…"` attribute overrides the TOC label (I §3.2.4).
- `TOC.xhtml`: `<div class="sgc-toc-title">Índice de contenido</div>`, then one `<div class="sgc-toc-level-N"><a href="../Text/x.xhtml">Label</a></div>` per entry.

### 1.5 CSS files and what is locked

| File | Status | Notes |
|---|---|---|
| `epl.css` | **LOCKED**: "NO MODIFIQUE ESTA HOJA DE ESTILOS" (I §3.1.1, §3.2.2). Its classes stay even when unused (II §2.07) | Reset + global classes (table below). Header comment `/* ePub base r2.1 ePubLibre - epl.css*/` is a fingerprint |
| `style.css` | Editor's sheet. All custom CSS goes here | Default `p { text-indent:1.5em; margin:0 }`, headings, `.dedicatoria`, `.saltoinicio` (25% top), `.sintop`, `.salto05/10/25`, `hr` variants, `.ilustra`, `h1+p, h2+p…, hr+p, blockquote+p, ol+p, ul+p, table+p, dl+p {text-indent:0}`, `blockquote.comilla`. **Must not set a default `font-size` on `p`** |
| `sgc-toc.css` | Editable; only linked from TOC.xhtml | |

- No inline `style=""`, no `<style>` in `<head>`, no Calibre auto-classes (I §3.2.5; ERROR 89).
- Discouraged because readers ignore them (III §2.02): `font-variant:small-caps`, `text-transform`, `letter-spacing`, `word-spacing`, `!important`, pseudo-elements (`:first-letter`…), `max-height`, `background` images, `<mark>`, `ol start`/`li value`, and links wrapped around images.

`epl.css` global classes, which are safe to rely on in any ePubLibre book (Base/epl.css):

| Purpose | Classes / elements |
|---|---|
| Font | `.sans` `.serif` `.mono` `code kbd samp var` |
| Style | `i em cite dfn .cursiva` (italic; italic nested in italic turns roman), `b strong .negrita`, `ins .subrayado`, `del s .tachado`, `big .grande`, `small .versalita` (0.8em), `.normal` |
| Alignment | `.izquierda` `.derecha` `.centrado` `.justificado` `.asangre` (no indent) |
| Blocks | `.sinmargen` `.bloque` (no page split) `.extenso` (ADE bug) `.oculto` (display:none) `abbr .nosep` (inline-block, no wrap) |
| Fixed pages | `.cubierta` `.tlogo` `.tautor` `.ttitulo` `.tsubtitulo` `.tserie` `.trevision` `.tfirma` `.tfecha` `.sinopsis` `.info` `.autor` `#iautor` `.vineta` `.nota` `.icono_fuente` `.bloque_exlibris` `.ancho_full` |
| Defaults | `hr` = invisible 2.5em gap. `h1–h6` centred, bold, 1.2em. Lists indented 9% |

---

## 2. Markup catalogue

**T** = translatable text. **N** = not translatable: preserve byte for byte.

### 2.1 Divisions and headings (I §3.2.1, §3.2.4; III §2.01)

| Element | Canonical markup | Notes |
|---|---|---|
| Hierarchy | `<h1>` = part/book/section, or chapter if there are no parts. `<h2>`, `<h3>`… = subordinate levels | Never skip a level (h1→h3 is ERROR 83 / TOC abort). Fixed sections are always `<h1>` (ERROR 84). Heading at the start of each file |
| Chapter | `<h1>Capítulo 1</h1>` | **T** |
| Display ≠ TOC label | `<h1 title="Capítulo 1">*** CAPÍTULO PRIMERO ***</h1>` | Both the text and `title` are **T**, and they must stay consistent with `toc.ncx`/TOC.xhtml |
| Two-line title | `<h1>1.<br/>El saltamontes</h1>` (one `<br/>` only, never chained), or `<h1>1.</h1><p class="subtitulo">…</p>` (`.subtit`), or `<h1 title="Parte I. X"><span>Parte I<br/></span>X</h1>` | Subtitle class names are editor-defined |
| Hidden heading | `<h1 class="oculto">8 de septiembre</h1>`, `<h1 class="oculto" title="8 de septiembre"/>`, or `<h1 title="8 de septiembre"/>` (empty, keeps the 25% top margin) | The `title`/text is **T** (TOC label) |
| Untitled section | `<p class="saltoinicio">First paragraph…</p>` | Class **N**. Text **T** |
| Image chapter head | `<h1 title="X"/>` + `<p class="ilustra"><img alt="" …/></p>`, or `<h1 class="ilustra" title="X"><img …/><br/>CAPÍTULO X</h1>` | |
| Part (typical) | A file whose only content is an `<h1>` (+ subtitle), followed by chapter files at `<h2>` | **(?)** inferred from the hierarchy rule |
| Note call in a heading | `<h1 title="Título">TÍTULO<a href="../Text/notas.xhtml#nt1" id="rf1"><sup class="font05">[1]</sup></a></h1>` | |

### 2.2 Breaks, spacing, first paragraph (Base/Section0001, style.css; I §2.2, §3.2.2; III §2.01)

| Element | Markup | Notes |
|---|---|---|
| Scene break (*salto de contexto*) | `<hr/>` (blank 2.5em), `<hr class="linea"/>` (short rule), `<hr class="imagen"/>` (asterisk image via CSS background), `<hr class="lineacorta"/>` | **N**. Preferred over spacing classes because readers without CSS still show it |
| Ornament paragraph | `<p class="asteriscos">* * *</p>` | **N** |
| Spacing | `<p class="salto05/salto10/salto25">`, `<p>&nbsp;</p>` (pause in letters, synopsis, poems; info page) | `<p>&nbsp;</p>` is **N**. Keep it as its own paragraph |
| First paragraph after heading/break | Unindented through CSS `h1+p, hr+p, blockquote+p, ol+p, ul+p, table+p, dl+p`, or explicitly `class="asangre"` | No class needed in r2.1 |
| Page break | `.breakbefore` / `.breakafter` on an element or an empty `p`/`div` | Editor-defined |
| Split marker | `<hr class="sigil_split_marker"/>` | Sigil artefact. Must not survive into a final book |

### 2.3 Inline semantics (I §3.2.2; II §5 *Cursiva*; III §1.2 *etiquetastexto*)

| Tag | Use |
|---|---|
| `<i>` | Foreign words not assimilated (*extranjerismos crudos*, Latin phrases), scientific names (genus and below), named vehicles (ships, planes, trains, spacecraft) and hurricanes, pet names (except classic or character animals), nicknames only when they follow or sit inside the name, slang or deliberate misspellings, neologisms, metalanguage, stage directions. Optional `xml:lang`: `<i xml:lang="en">…</i>` |
| `<cite>` | Titles of books, periodicals, films, TV and radio programmes, artworks, music (and their acronyms) |
| `<em>` | Author emphasis |
| `<dfn>` | First occurrence of a defined term |
| `.cursiva` | Purely decorative italic |
| `<strong>`/`<b>` | Headings-like labels, warnings, emphasis that should catch the eye |
| `<small>` | **Small caps**: the text is typed in UPPERCASE inside `<small>` (0.8em). Example: `M<small>IGUEL DE</small> C<small>ERVANTES</small>`, `siglo <small>XXI</small>`. Never `font-variant` |
| `<abbr>` | Abbreviations and formulas (`<abbr>a. C.</abbr>`, `<abbr>C<sub>2</sub>H<sub>6</sub>O</abbr>`). No wrap |
| `<span class="nosep">` | Keep a group on one line: dates `01-01-2000`, `L<small>ÁZARO</small>` |
| `&nbsp;` | Inside multi-part abbreviations and initials (`T.&nbsp;S. Eliot`, `EE.&nbsp;UU.`, `a.&nbsp;C.`) and number groups (§3.7). Written as the entity `&nbsp;` in the manuals' source. The validator warns "Posible nosep o nbsp innecesario" |
| `<sup>`/`<sub>` | Typographic only (formulas, note markers) |

### 2.4 Notes, the main structure to preserve (Base/notas.xhtml; I §3.2.3, §3.3.2.4; II §3.01–3.02)

```html
<!-- in the body: call glued to the word, normally BEFORE punctuation (French system, §3.9) -->
<p>En un lugar de la Mancha<a href="../Text/notas.xhtml#nt1" id="rf1"><sup>[1]</sup></a> de cuyo nombre…</p>
<!-- in notas.xhtml: one div per note -->
<div class="nota">
  <p id="nt1"><sup>[1]</sup> Es un lugar imaginario de la Mancha. <a href="../Text/c01.xhtml#rf1">&lt;&lt;</a></p>
</div>
```
- IDs: `rfN` (call, in the body) ↔ `ntN` (note). Numbering is consecutive across the book. N appears three times in each block. The backlink points to the file holding the call. The ePLValidator checks this format (ERROR 88).
- **N**: the `<a>` elements, ids, hrefs, `<sup>[N]</sup>` (rendered as "[1]"), and the backlink text `&lt;&lt;` (rendered as "<<"). **T**: the note text between `</sup> ` and ` <a`.
- Editor or translator notes end with `(N. del E. D.)`/`(N. de la E. D.)`, or `(N. del T.)`/`(N. de la T.)` (I §3.2.3). A regex italicises them (§4.3).
- Multi-paragraph notes are not covered by the manuals **(?)**. Expect extra `<p>` inside `div.nota`, with the backlink on the last one.
- Non-ePL note markup from sources (e.g. `ref_footnotebookmark_start`) is converted to this pattern by regex (II §3.02).

### 2.5 Epigraphs, dedications, quotations, letters (Base; I §2.2, §3.2.2)

| Element | Markup |
|---|---|
| Epigraph (template) | `<blockquote><p class="asangre">Quote text.</p><p class="derecha salto05">M<small>IGUEL DE</small> C<small>ERVANTES</small>,<br/><cite>Don Quijote de la Mancha</cite></p></blockquote>` at the top of the chapter file |
| Quote with image | `<blockquote class="comilla"><p class="asangre">…</p></blockquote>` (italic, comilla1.png) |
| Block quotation / letter / press clipping | `<blockquote><p>…</p></blockquote>`. Text must sit inside `<p>`, never bare in a blockquote (FlightCrew error, I §3.3.2.3). Signature: editor class such as `.firma` (right, italic, padding) or `<p class="derecha cursiva salto25">` |
| Dedication | `dedicatoria.xhtml` `div.dedicatoria` (right-aligned, 25% top margin) |
| Italic-only blocks (dedication, epigraph) | Roman and italic swap roles inside them (II §5 *Cursiva*). The CSS renders nested `<i>` as roman |

### 2.6 Poetry, lists, tables, images, drop caps (III §2.01, §3.01, §3.03, §4.x)

| Element | Markup (classes are editor-chosen examples, **not** standard names) |
|---|---|
| Poem | `<div class="verso"><p>line</p><p>line</p></div>` (one `<p>` per line, `text-indent:-2em` hanging). Stanzas: separate divs, `<p>&nbsp;</p>`, or `.salto10`. Centred variants: `.centrarversos > .versoscen`, `.centrarpoema > .poemacen` + `<div class="clear"></div>`. Line numbers: `<span class="numerosder|numerosizq">12</span>` (**N**). Older books may use `.cita` (III §2.01). The manuals have no `poema`/`stanza` classes **(?)** |
| Marginal notation | `<span class="numarg">402a</span>` with `body.notmarg`. Side notes: `<span class="colnota">` inside `div.coltexto` |
| Lists | `<ol>/<ul><li>`, `<dl><dt>Term:</dt><dd>…</dd></dl>`. No `start`/`value`: unusual numbering is typed into the text (III §2.02) |
| Tables | `<table><caption>…</caption><tr><th>…</th><td>…</td></tr></table>`. Also used for poetry layout. `caption-side` is unsupported |
| Images | `<p class="ilustra"><img alt="" src="../Images/x.jpg"/></p>` (or `div`). Full-page image: `<body class="sinmargen">` + image only. Caption: `div.contenedorpie > div.imagen + p` (or `.pie`). `alt` is usually empty. SVG may be an image file or inline, and SVG exported "as text" contains real `<text>` (IV §SVG03) |
| Drop cap | `<p class="asangre"><span class="capital">P</span>árrafo…</p>`. With a leading sign: `<span class="precapital">–¿</span><span class="capital">Q</span>ué…` (semirraya allowed here, II §5 *Raya*). Also `.capalta`, `.capitular` |
| Centred / right text | `.centrado`, `.derecha`, `.dere` (20% left padding, editor class), `.francesa` (hanging indent) |
| Foreign word | `<i xml:lang="fr">…</i>` |

---

## 3. Spanish ortotipografía (rules to apply to translated text)

Notation: `·` = a required space, `⍽` = a non-breaking space (`&nbsp;`), `∅` = no space.

### 3.1 Quotation marks (II §5 *Comillas*, *Diálogos*; I §3.3.2.2)

| # | Rule | Example |
|---|---|---|
| Q1 | Nesting order: `« »` first, then `“ ”`, then `‘ ’` | `«Antonio me dijo: “vaya ‘cacharro’ se ha comprado Julián”».` |
| Q2 | No straight quotes `"` `'`. Apostrophe = `’`. Exception: `″`/`′` measures, which the manual still writes straight | `52° 2' 20"` |
| Q3 | Punctuation belonging to the containing sentence goes **after** the closing quote | `Sus palabras fueron: «No lo haré»; pero…` / `¿De verdad ha dicho «hasta nunca»?` |
| Q4 | The quoted text keeps its own `? ! …`, but the sentence-final period always goes **outside**, even after `?`/`!`/`…` inside | `«¡Qué ganas tengo!», pensó.` / `«Si pudiera…». A Pedro…` / `«¡Menudo golpe!». Marcos…` |
| Q5 | Thoughts are framed in `« »`. Quotes inside thoughts use `“ ”`, then `‘ ’` | `«¡Hasta en latín sabía maldecir!», pensó el padre.` |
| Q6 | A quotation, thought or speech running over several paragraphs: each continuation paragraph **starts with `»`** (closing guillemet, glued) | `»Y había toda clase de recovecos…».` |
| Q7 | `« »` also for: titles of *parts* of works (articles, poems, chapters, while the work itself goes in `<cite>`); ironic or improper words; quotations inline. Single quotes `‘ ’` for meanings in linguistics | `el artículo «El léxico de hoy» en <cite>El lenguaje…</cite>` |
| Q8 | An author attribution inside a quotation goes between rayas. Outside it, use a comma | `«Es imprescindible —señaló el ministro— reforzar…»` |

### 3.2 Dialogue with raya (II §5 *Diálogos*, §5 *Raya*; II §5 *Mayúsculas*)

| # | Rule | Example |
|---|---|---|
| D1 | Each speech turn is its own paragraph and starts with `—` glued to the first word (`<p>—∅Word`) | `—¿Qué fue eso?` |
| D2 | Narrator inciso: space before the opening `—`, no space after it. The closing `—` is glued to the last word of the inciso | `—¿Qué fue eso? —preguntó Beregond—. ¿También tú…?` |
| D3 | If the speech does **not** continue after the inciso, there is **no closing raya**, and the paragraph never ends in `—` | `—¿Qué fue eso? —preguntó Beregond. Nadie le contestó.` |
| D4 | Speech interrupted by the inciso: the punctuation of the interrupted sentence goes **after** the closing raya, never before the opening one | `—Está bien —dijo Carlos—, lo haré…` (not `—Está bien, —dijo…`) |
| D5 | Speech ending before the inciso keeps its own `.?!…` before the raya. If speech resumes, the period or colon that ends the inciso goes after the closing raya | `—¿Puedo irme ya? —Se puso en pie—. No hace falta…` / `—…fiesta —me confesó, y añadió—: Conocí…` |
| D6 | A speech verb (*decir, añadir, preguntar, exclamar, responder…*) starts the inciso in lowercase. Any other verb requires the speech to close with a period and the inciso to start in uppercase | `—¡Qué le vamos a hacer! —exclamó…` / `—No se moleste. —Cerró la puerta…` |
| D7 | Multi-paragraph speech: continuation paragraphs start with `»` (not `—`) | see II §5 *Diálogos* example |
| D8 | Narrative incisos (outside dialogue) are always paired, even at the end of a sentence. The final punctuation goes after the closing raya | `…varias obras —todas de su primera época—.` / `…a Emilio —el autor—, que…` |
| D9 | Raya also replaces an omitted repeated word or words (lists, indexes) | |

### 3.3 Raya vs semirraya vs guion vs minus (II §5 *Raya*; I §3.3.2.2)

| Char | Code | Use |
|---|---|---|
| `—` raya U+2014 | `&mdash;` | Dialogue, incisos, attribution in quotes, omitted words |
| `–` semirraya U+2013 | `&ndash;` | "En español no suele utilizarse". Only in a *precapital* with a drop cap. ePLValidator ERROR 90 flags wrong characters used as raya |
| `-` guion U+002D | | Compounds (`científico-técnico`), coordinated prefixes (`intra- o extrabdominal`), syllable breaks, prefix + capital or digit (`pro-Obama`, `sub-21`). Never as a dash |
| `−` menos U+2212 | `&minus;` | Subtraction and negative numbers. Never the semirraya |

### 3.4 Ellipsis and simple punctuation (II §5 *Puntuación*, *Siglas*; I §3.3.2.2)

- E1: `...` → `…` (U+2026, a single character). `[...]`/`(...)` → `[…]`, which marks an omission in a quotation (not needed at the very start or end).
- E2: Never put `.` after `…`, `?` or `!`. An abbreviation plus ellipsis gives four dots: `etc.…`.
- E3: Never double the period: a sentence ending in an abbreviation keeps one period (`2 págs. No…`). A superscript-letter abbreviation still takes the final one (`la 3.ª.`).
- P1: Simple signs `. , : ; …` are glued to the preceding word and followed by a space. Double signs `¿? ¡! () [] — — « »` are glued inside and spaced outside. A following sign is glued to the closing one (`«¡Alto! ¡No sigas!», pensó.`).
- P2: `¿`/`¡` must open every question or exclamation, including partial ones: `Pero ¿dónde vas?`.
- P3: No comma after *pero* before `¿`/`¡`. A salutation in a letter takes a colon, not a comma (`Querido amigo:`). The comma is an anglicism.
- P4: Comma or other punctuation after an abbreviation goes after its period (`págs.,`).
- P5: No final period in isolated titles, subtitles, chapter headings or author lines.
- P6: Statements ending in `»`, `)` or a closing `—` always take a final period after them: `(¡Vaya genio!).`

### 3.5 Italics vs quotes vs roman (II §5 *Cursiva*; I §3.2.2, §3.3.2.2)

- Italic: work titles (`<cite>`), raw foreign words and Latin phrases (RAE 2010), neologisms, slang, metalanguage, named vehicles, scientific names. In a translation, **words that appear in Spanish in the original go in italics**, optionally with a note "En español en el original" (II §5 *Cursiva*; I §3.2.2).
- Roman: proper names (even foreign ones, e.g. `The Rolling Stones`), adapted loanwords (`yogur`, `currículum`), onomatopoeia and interjections, figures and unit symbols (even inside italic text).
- A title inside a title: the inner title's italics become `« »` (`Ensayos sobre «Lo que el viento se llevó»`). A shortened title keeps italics only on the remaining part (`el <cite>Quijote</cite>`). Foreign titles keep their own capitalisation.
- Punctuation takes the format of the word it touches, and paired signs take the format of their whole content. A note call inherits the emphasis of its word (II §5 *Cursiva*, non-RAE, optional).

### 3.6 Capitalisation (II §5 *Mayúsculas*, *Acentuación*; I §3.1.2, §4.1)

- Uppercase after `.`, after a sentence-closing `…`, `?` or `!`, at the start of a quotation after a colon, after a letter salutation (`Querido Andrés: Recibí…`), and in a non-speech inciso (D6).
- Lowercase: days, months and seasons; languages, peoples and demonyms; religions; currencies; titles and ranks (*rey, papa, duque, doctor*); courtesy forms (*don, señor, sor, fray*), whose abbreviations are capitalised (`Sr.`, `Ud.`, `Dra.`); cardinal points (except in proper names); disciplines; parts of a work (`el capítulo 7`); `-ismos` and artistic periods; generic categories (`el río Ebro`).
- **Titles of works use sentence case** (*mayúsculas normalizadas*): only the first word and proper nouns are capitalised (`Últimas tardes con Teresa`). Periodical names capitalise every noun and adjective (`Revista de Ideas Estéticas`).
- Capitals keep their accents (`ÁNGEL`, `CÉSPED`); acronyms do not (`CIA`).
- Roman numerals are always uppercase letters, in small caps after a lowercase noun (`siglo <small>XIX</small>`) and full capitals otherwise (`Alfonso X`, `II Congreso`). They never take a superscript ordinal (`II.ª` is wrong).

### 3.7 Numbers, symbols, abbreviations (II §5 *Números*, *Siglas*, *Prefijos*)

| # | Rule | Right / wrong |
|---|---|---|
| N1 | Literary text: write numbers in words, unless the number needs 4 or more words. Don't mix words and figures in one statement. Set phrases always use words | `cinco libros`, `32⍽423 habitantes` |
| N2 | Groups of three digits separated by a space (`&nbsp;` in the manuals' source), never by `.` or `,`. Decimal comma | `8⍽327⍽451` (not `8.327.451`, not `8,327,451`). `3,1416` |
| N3 | No separator in years, pages, verse numbers, street numbers, postcodes, legal articles | `año 2001`, `página 3142` |
| N4 | Ordinal abbreviations: digit + `.` + superscript letters with `º`/`ª` (U+00BA/U+00AA) | `1.º`, `3.ª`, `1.er`, `n.º` |
| N5 | Degree sign `°` (U+00B0), not `º` (U+00BA). With a scale: `12⍽°C`. Without one: `12°` | |
| N6 | Unit and percentage symbols are separated from the number by a space and never wrapped to the next line. They take no period, no plural and no accent | `25⍽%`, `4⍽km`, `18⍽$` (America may write `$50`) |
| N7 | Abbreviations always end in `.` and keep their accents (`pág.`). Multi-word abbreviations are spaced (`EE.⍽UU.`, `a.⍽C.`, `b.⍽l.⍽m.`). They must never be split across lines or left alone on a line | |
| N8 | Acronyms (siglas) are uppercase, with no periods, spaces, accents or plural `s` (`ONG`, not `ONGs` or `CD’s`). Use the Spanish form where it exists (`OTAN`, not `NATO`). Lexicalised ones are lowercase (`ovni`, `sida`). Proper-noun acronyms of 5+ letters use initial capital (`Unesco`) | |
| N9 | Prefixes: glued to a one-word base (`exnovio`, `posventa`), hyphenated before a capital or digit (`pro-Obama`, `sub-21`), spaced before a multi-word base (`ex relaciones públicas`) | |
| N10 | No tilde on `o` between figures (`1 o 2`), `solo`, demonstratives, or `guion`/`rio` (RAE 2010) | |

### 3.8 Spaces and special characters (I §3.3.2.2; III §2.01)

- Replace HTML entities with the real characters (`…`, `—`, `–`, `«»`, `“”`, `‘’`, `°`, `ª`, `º`) where the character exists. Keep `&nbsp;`, `&lt;` and `&gt;` as entities.
- `&nbsp;` is allowed inside abbreviations and initials, number groups and number+symbol pairs. Otherwise use `<span class="nosep">`.
- Check unusual characters with Sigil's *Informes → Caracteres en ficheros HTML*. ERROR 91 flags combining or wrong characters.

### 3.9 Note calls (II §5 *Llamadas a notas*; I §3.2.3)
- ePubLibre prefers the **French system**: the call goes immediately **before** simple punctuation (`estudios[1].`). After an ellipsis the call follows it and a period follows the call (`Moma… [3].`). With paired signs, the call goes inside if it refers to the last word (`Mastrique[1]?`) and outside, followed by a period, if it refers to the whole segment (`Mastrique?[2].`).
- The English system (call always after punctuation) is valid but must be used consistently. I §3.2.3 says to keep punctuation, quotes and brackets out of the link.

---

## 4. Workflow and QA

### 4.1 Production steps (I Part 3)
1. Copy the base. Set a new UUID BookId (Sigil, the web generator, or ePLValidator auto). Regenerate the TOC.
2. Fill in the metadata (§1.2) and regenerate the TOC after every OPF change.
3. Replace `cover.jpg` (600×900 to 1200×1800, 2:3 ratio, ≤ 300 KB, ePubLibre logo, publisher logos removed, *Imagen de portada* concept set) and `autor.jpg` (jpg, ≤ 600×400).
4. Complete the fixed pages: sinopsis = description, titulo, info, dedicatoria, autor, notas. Delete unused optional files.
5. Lay out the content: one chapter per file, ≤ 300 KB, heading hierarchy, styles in style.css, always in Code View.
6. Add notes (§2.4) and generate the TOC from the headings.
7. Clean dirty code (Calibre classes, inline styles, empty spans) and merge repeated classes (I §3.3.2.3).
8. Correct the text: saved-search RegEx groups run in order, **case by case, never "replace all"** (I §3.3.1). Spell-check with the community Hunspell dictionary **`c2c_1_epublibre.aff/.dic`** (1 101 661 words, II §2.02) and compare sources with Beyond Compare or Calibre's *Comparar con otro libro*. Optionally proofread by reading ("verificado").
9. Typographic pass: homogeneous styles, scene breaks checked against other editions, italics and *extranjerismos crudos*, small caps (mandatory for Roman numerals after a lowercase noun), special characters (I §3.3.2.2).
10. EPL-standard checklist (I §3.3.2.4): UUID ≠ base, unused styles removed, XHTML ≤ 300 KB, note format, metadata and series, fixed pages unmodified, revision and date in titulo, TOC regenerated, validators run.
11. Validate with **all** of FlightCrew (Sigil, F7), EpubCheck (IDPF, 3.0.1, online ≤ 10 MB or offline jar), the W3C css-validator, and **ePLValidator** (EPL standard; may give false positives) (I §0.5, §3.4).
12. Name the file (I §4.1) and upload it (I Part 4).

### 4.2 ePLValidator checks worth replicating (I §3.4.5, selection)
Metadata missing, empty or repeated (02–04). Description, title, date or images still the base defaults (05, 25, 43, 57, 61). Publisher ≠ `ePubLibre` (07). Title, author, translator, series or revision mismatches across OPF, titulo, info, ncx and file name (08, 26–32, 50–55, 60–65). file-as missing or malformed (33–36). Several authors not written `AA. VV.` (37). XHTML > 300 KB (39). Cover size (40). Heading hierarchy not starting at h1, or fixed section headings not h1 (83–84). Fixed-section code modified (85). Non-standard notes code (88). Code in `<head>` (89). Wrong raya character (90) or combining characters (91). Files missing or unreferenced (96–98). Warnings: text outside a container, embedded font lacking a glyph ("El estilo %s no dispone del carácter %s"), `lang` and `<title>` recommended on every section, old base version.

### 4.3 Regex battery
The official battery (`sigil_searches.ini`, groups "0. Limpieza de código", "1. Comillas"…, entries 0.01…) is **not shipped in the manuals**. Candidates get it from their reviewer (I §3.3.1). Per I §3.3.1–3.3.2.2 it covers OCR errors, raya position, straight → angular quotes, lowercase after a period, `...` → `…`, raw foreign words and Latin phrases → italics, lowercase Roman numerals, and uppercase → small caps. Sigil uses PCRE, with `\pL` for letters including accents, `(?|…)` duplicate group numbers, and `\U \L \E \u` in replacements (II §4.x, §2.09). The regexes the manuals do show:

| Purpose | Find | Replace | Source |
|---|---|---|---|
| Italicise N. del T./E. | `(?<!i>\|em>)(\(N. de(.*?)\))` | `<i>\1</i>` | I §3.3.2.1 |
| Italicise foreign words | `(?<!em>\|i>)(miss\|sir\|lady)` | `<i>\1</i>` | I §3.3.2.2 |
| Plain `[n]` → note call | `\[([0-9]*)]` | `<a href="../Text/notas.xhtml#nt\1" id="rf\1"><sup>[\1]</sup></a>` | II §3.02 |
| Split markers before merging | `<body>` | `<body>\n<hr class="sigil_split_marker"/>` | I §3.3.2.1 |
| Paired em/strong | `<(?\|(em)\|(strong))>[^<]+</\1>` | (search) | II §4.08 |

Derived QA checks for our tool. Run them on paragraph **text** with tags removed and `&nbsp;` decoded as U+00A0 unless noted; they are not from the manuals:

```python
QA = {  # id: (pattern, meaning)  — Python `re`, flags=0
 "Q2_straight":   (r"[\"']", "straight quote/apostrophe → « » “ ” ‘ ’ / ’"),
 "Q4_period_in":  (r"(?<!\.)\.(?=[»”’])", "final period inside closing quote (ok only if abbreviation)"),
 "Q4_no_period":  (r"[?!…][»”]\s+(?=[A-ZÁÉÍÓÚÑ¿¡«—])", "missing '.' after closing quote before new sentence"),
 "Q1_nest":       (r"«[^»]*«", "angular inside angular → use “ ”"),
 "D1_open":       (r"^(?:[-–]\s?|—\s)", "dialogue must open with '—' glued to word (precapital excepted)"),
 "D3_end":        (r"—\s*$", "paragraph must not end with a raya"),
 "D2_spaced":     (r"\s—\s", "raya with spaces on both sides"),
 "D2_glued":      (r"[A-Za-zÁ-úñÑ]—[A-Za-zÁ-úñÑ]", "raya between letters (English em-dash style) → ' —inciso— '"),
 "D4_comma":      (r"[,;]\s—[a-záéíóúñ]", "punctuation before inciso → move after closing raya"),
 "D6_case":       (r"\.\s—[a-záéíóúñ]", "period then lowercase inciso (speech verb ⇒ drop period; else capitalise)"),
 "S_spdash":      (r"\s[-–]\s", "spaced hyphen/en dash used as dash → raya"),
 "E1_dots":       (r"\.\.\.", "three dots → …"),
 "E2_after":      (r"[…?!]\.", "period after …/?/! (abbrev+… is '.…', which is fine)"),
 "P1_sp_before":  (r"\s[,.;:?!…»”’)\]]", "space before closing/simple punctuation"),
 "P1_sp_after":   (r"[«“‘¿¡(\[]\s", "space after opening sign"),
 "P1_no_sp":      (r"[,;:](?=[^\s\d»”’)\]—<])", "missing space after , ; :"),
 "P2_inv":        (None, "per paragraph: count('¿')==count('?') and count('¡')==count('!')"),
 "P3_pero":       (r"\b[Pp]ero,\s*[¿¡]", "no comma after 'pero' before ¿/¡"),
 "P3_salut":      (r"^(?:Querid|Estimad|Apreciad)[oa]s?\b[^:.]{0,60},\s*$", "letter salutation comma → colon"),
 "N2_thou":       (r"\b\d{1,3}(?:[.,]\d{3})+\b", "thousands with . or , → nbsp groups (not years)"),
 "N2_dec":        (r"\b\d+\.\d+\b", "decimal point → decimal comma (review: versions, times)"),
 "N4_ord":        (r"\d(?:[ºª]|°(?=[a-z]))", "ordinal needs '.' + º/ª: 1.º 3.ª"),
 "N5_deg":        (r"\d\s?º\s?[CFK]\b", "degree with º (ordinal) → °; '12 °C'"),
 "N6_sym":        (r"\d(?:%|(?:km|kg|cm|mm|ml|m|g|l)\b)", "number glued to symbol → '25 %'"),
 "C_months":      (r"(?<![.?!…]\s)(?<!^)\b(?:Lunes|Martes|Miércoles|Jueves|Viernes|Sábado|Domingo|Enero|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto|Septiembre|Octubre|Noviembre|Diciembre)\b", "days/months lowercase mid-sentence"),
 "C_roman":       (r"\bsiglo\s+[ivxlcdm]+\b", "Roman numeral must be uppercase (small caps)"),
 "NC_english":    (r"[.,;:]<a [^>]*id=\"rf\d+\"", "[raw XHTML] note call after punctuation (English system)"),
 "WS_double":     (r"  +", "double space"),
}
```
D6 and N2_dec produce false positives and are review-only. P1 must skip `»` that opens a continuation paragraph and `…` that opens a quotation (`«… y los sueños`).

---

## 5. Implications for the translator

### 5.1 Recognising an ePubLibre EPUB
Strong signals (any two together are conclusive):
- `<dc:publisher>ePubLibre</dc:publisher>`, `<dc:identifier opf:scheme="EPL">`, `<dc:identifier opf:scheme="revision">`.
- `Styles/epl.css` whose first line is `/* ePub base rX.Y ePubLibre - epl.css*/` (bases before r2.0 had a single `style.css` with a fixed first section "ESTILOS GLOBALES Y DE SECCIONES FIJAS" **(?)**, per ERROR 14–16).
- Spine starting `cubierta, sinopsis, titulo, info` and ending `autor, notas`. `info.xhtml` containing `ePub base r\d\.\d`. `titulo.xhtml` with `tautor/ttitulo/trevision/tfirma`. Images `EPL_logo.png` and `ex_libris.png`. File name `… [\d+] (r\d\.\d …)`.

Structure detection:

| Need | Signal |
|---|---|
| Front and back matter (translate selectively) | Spine position + file names `cubierta/sinopsis/titulo/info/TOC/dedicatoria/autor/notas` + guide types |
| Part vs chapter | `<h1>` file followed by files at `<h2>`, otherwise `<h1>` = chapter. Hierarchy never skips levels |
| Chapter title for the TOC | `h1–h6` text, overridden by the `title` attribute, which may sit on empty or `.oculto` headings |
| Untitled section start | `p.saltoinicio`, or an empty `<h1 title="…"/>` |
| Scene break | `<hr>` (any class), `p.asteriscos`, `p.salto25`/`salto10`, `<p>&nbsp;</p>`. Translate none of them |
| Notes | `a[id^=rf][href*="#nt"] > sup` in the body, `div.nota > p[id^=nt]` in notes files, backlink `a` with text `<<` |
| Verse, letters, quotes | Container tag (`blockquote`, `div`) + one-`<p>`-per-line pattern. Classes are editor-specific and only hints |

### 5.2 Preserve byte for byte
File names and paths. OPF manifest and spine order. All ids (`rfN`, `ntN`, `iautor`, Sigil TOC ids), hrefs and `src`. Class lists. The `xml:lang` structure (but see §5.4). `epl.css` (locked) and `sgc-toc.css`. `cubierta.xhtml` entirely. Comments. `<hr …/>`, `<p>&nbsp;</p>`, `* * *` ornaments. Note markers `<sup>[N]</sup>`, backlink `&lt;&lt;`, line-number and marginal spans. `<br/>` count inside headings and verse. Images, `svg` attributes, the `ePub base rX.Y` line, the logo and ex libris blocks.

### 5.3 Must change or keep in sync when the text changes
- `dc:title` = `h1.ttitulo` = ncx `docTitle`. Heading text and `title` attributes = `toc.ncx` `navLabel` = `TOC.xhtml` links. Our tool must rewrite all of these together, because it cannot "regenerate" the TOC the way Sigil does.
- `sinopsis.xhtml` text = `dc:description` (plain text, italics → `« »`).
- `info.xhtml`: keep `Título original` in the source language, wrapped in `<cite>`. Add or keep `Traducción: …` and keep it identical to `dc:contributor opf:role="trl"` with `file-as` (ERROR 31/32). `dc:language` becomes `es`, and `xml:lang="es"` goes on every `<html>`.
- Drop caps and small caps wrap *characters*, not words: `<span class="capital">P</span>árrafo`, `T<small>HE FIRST</small>`. Re-apply them to the first letter or words of the Spanish text, in uppercase inside `<small>`.
- Note calls: keep each call attached to the translated word it annotates, and move it before punctuation (French system, §3.9) only if the target book adopts that style consistently.
- **Size**: Spanish runs roughly 15–25 % longer than English **(?)**. An XHTML near 300 KB in the source can break ERROR 39, so split files at chapter or section boundaries only, which changes the file list.
- **Embedded fonts**: a subset font from the source may lack `ñ ¿ ¡ « » á é í ó ú ü —`. Check glyph coverage (validator "no dispone del carácter").
- Adding translator notes means renumbering every later `rfN`/`ntN` and backlink. Prefer appending notes in reading order, or avoid adding them **(?)**.

### 5.4 Spanish rules for the target style, conflicts with English sources

| English source convention | Spanish (ePubLibre) target | Effect on structure |
|---|---|---|
| `“Hello,” he said. “How are you?”` | `—Hola —dijo él—. ¿Cómo estás?` (D1–D6) | Punctuation inside the paragraph changes. **Paragraph count is unchanged** |
| A paragraph of narration followed by a quoted line | `Hizo una pausa. —Ven aquí —dijo.` is accepted in Spanish fiction **(?)**. The manuals only describe dialogue paragraphs that start with a raya | Keep the paragraph and do not split it |
| Multi-paragraph speech: `“` opens each paragraph, no `”` until the end | First paragraph `—…`, later ones start with `»` (D7) | Same paragraphs |
| Quote inside dialogue `“… ‘x’ …”` | Inside a raya speech the first level becomes `« »`, then `“ ”`, then `‘ ’` | |
| Non-dialogue quotes `“scare quotes”` | `«…»` (Q1). Period and comma outside (Q3/Q4) | |
| Thoughts in *italics* | ePubLibre prefers `«…», pensó` (Q5). Keeping italics is acceptable if consistent (II §5.1 "orientativas"). **Decide once per book** | Changes inline tags (`<i>` removed) |
| Em dash interruptions `word—word`, spaced en dash ` – ` | Narrative inciso `palabra —inciso— palabra`. An interrupted speech ends `…` or `—` **(?)** | |
| Title Case in headings and titles | Sentence case (*mayúsculas normalizadas*) | |
| `Mr./Mrs./Dr.` | `señor/señora` or `Sr./Sra./Dr.` before a name. Untranslated `miss/sir/lady` → `<i>` | |
| `1,000.5`, `25%`, `5km`, `1st` | `1000,5` (`10⍽000` from five digits), `25⍽%`, `5⍽km`, `1.º`/`primero` | |
| Months and days capitalised | lowercase | |
| `?!` without opening signs | Add `¿` and `¡` at the real start of the question or exclamation (P2) | |
| Spanish words in the English original | Italicise them, optionally with the note "En español en el original" | |
| English text kept untranslated (songs, letters) | `<i xml:lang="en">` or `xml:lang="en"` on its block | |
| Comma after a letter salutation | Colon | |
| Note calls after punctuation | French system preferred (§3.9). Either is valid if consistent | |

ePubLibre's own rules forbid publishing unofficial translations on the site without approval, and such translations use a separate logo (I §0.4, §0.5). A machine-translated output should therefore not present itself as an ePubLibre release. How the titulo, info and logo are handled is a product decision for us **(?)**.
