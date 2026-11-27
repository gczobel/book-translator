# How Professional Book Translators Work & Mapping the Craft to a Deterministic LLM Pipeline

> Research compiled by the `Translation Craft Researcher` sub-agent (`98c9ba65-b0a9-489c-9265-c346b86c557b`).

---

## 1. The Professional & Cognitive Craft (How Translators Think & Prepare)

### 1.1 Pre-Translation Reading & Narrative Analysis
Professional book translators divide into two well-documented camps on whether to read the entire book before translating page one:

* **The "Read the Whole Book First" Camp (Majority / Macro-First):**
  Advocated by translators such as **Edith Grossman** (though late in life she experimented with the blind method for the thrill of surprise; [*The Guardian*](https://www.theguardian.com/books/2023/sep/14/edith-grossman-obituary)) and emphasized in standard guides (CEATL, ATA). Translating Chapter 1 without knowing Chapter 20 risks breaking foreshadowing, misreading an unreliable narrator, or altering a recurring motif whose structural payoff only appears at the end.
* **The "Start Immediately / Present-Tense Discovery" Camp:**
  Championed by **Gregory Rabassa** (translator of García Márquez and Cortázar), who argued that reading ahead destroys immediacy: *"When you translate a book, it's entirely in the present, because you haven't read it entirely yet. If I go back and read it, the present is no longer the present, it's past."* **Daniel Hahn** similarly prefers not to read ahead when possible, treating the first draft as real-time discovery ("very quick and very bad"), and **Ann Goldstein** reads quickly before diving straight into drafting to preserve momentum. **Lydia Davis** has also noted resisting conventional reading-ahead to stay attentive to sentence-level surprise.
  *Note:* Even "blind starters" perform multi-pass revisions afterward, meaning macro-corrections discovered in Chapter 20 are retrofitted onto Chapter 1 during comparative revision passes.

During pre-translation / macro-analysis, translators systematically diagnose:
1. **Voice & Register:** Narrative persona (archaic, clinical, lyrical, colloquial), sentence-length distributions, and idiolects per character.
2. **Narrator Distance & Free Indirect Discourse (FID):** Calibrating the psychological focal length between an ironic/detached narrator and a character's interior consciousness. As Kristiina Taivalkoski-Shilov notes ([ACL Anthology W19-7305](https://aclanthology.org/W19-7305/)), FID (*discours indirect libre*)—grammatically third-person narration infused with a character's vocabulary, deictics, and emotional heat—frequently collapses in asymmetrical tense/aspect pairs (e.g., French *l'imparfait* vs. English simple past) unless preserved via syntax, modal verbs, and adverbials.
3. **Tense as Temporal Scaffolding:** Distinguishing deliberate tense shifts (e.g., historical present slipping into conditional/gnomic present to trigger focalization shifts) from accidental grammatical variation; standardizing erratic literary tenses destroys psychological pacing.
4. **Rhythm, Cadence & Meter:** Prose breath and syntactic pacing. For verse/epic translation, **Emily Wilson** (*The Odyssey*, 2017) rejected free verse in favor of **iambic pentameter** combined with a strict **line-for-line** constraint to mirror Homer's pace.
5. **Structural Motifs & Deliberate Repetition:** Identifying recurring imagery clusters, syntactic parallelisms, and lexical leitmotifs. Because target style norms (especially English) penalize repetition and push toward synonym variation ("elegant variation"), unguided translators often shatter load-bearing thematic echoes.

---

### 1.2 External Research, Paratext & Author Consultation

#### Paratext (Gérard Genette's Framework)
Translators analyze and produce both **peritexts** (inside the book: prefaces, afterwords, translator's notes, glossaries, epigraphs, chapter titles, footnotes) and **epitexts** (outside the book: author interviews, launch essays, publisher blurbs, reviews) to understand how the work is positioned in the source culture and framed for target readers.

#### Source-Culture Criticism, Reviews & Existing Translations
* **Reviews & Literary Criticism:** Source-language reviews and academic papers alert translators to what critics recognize as the author's signature techniques (e.g., deliberate syntactic subversion, political subtext, regional slang) and prevent "smoothing out" intentional roughness.
* **Retranslation & Existing Translations:** When retranslating a classic or consulting translations into *other* third languages, translators compare macro-strategies (omissions, domestication/foreignization) and micro-solutions (knotty metaphors), while guarding against **anchoring bias** (unconsciously mimicking or knee-jerk reacting against a predecessor).

#### Domain Research, Wikis & Non-Fiction Verification
* **Fiction World-Building:** Maps, dramatis personae, fan wikis (for series/franchises), historical timelines, flora/fauna, and period realia.
* **Non-Fiction & Scholarly Apparatus:** Translators act as de facto first-line fact-checkers:
  * **The "Back-Translation Trap" for Quotes:** If a source book quotes Shakespeare, Marx, or a primary study in the source language, the translator **must locate the original/canonical target-language edition** via **Google Books**, academic archives, or library catalogs rather than back-translating the source author's translation.
  * **Wikipedia's Proper Role:** Used strictly for rapid orientation, institutional names, and **interlanguage links** to find established target-language equivalents for historical events/concepts—never cited directly as an authoritative academic source.
  * **Factual Errors & Citations:** Dates, statistics, and misspelled names are flagged for the editor rather than silently altered (or resolved via discreet `[Translator's Note]`). Bibliographies are updated with official target-language titles where published editions exist; citation styles are adapted (e.g., Chicago/APA); and **back-of-the-book indexes cannot be translated**—they must be rebuilt from scratch after final pagination because word order, alphabetization, and conceptual groupings change.

#### Contacting the Author (or Literary Estate)
* **Timing:** Typically *after* completing a close read and exhausting dictionaries/encyclopedias so queries are sharp, numbered, and substantive.
* **What to Ask:** Intentional ambiguities, nonce words, dialect nuances, ambiguous pronouns, or whether broken syntax reflects character panic vs. stylistic quirk.
* **Two Stances:** Collaborative (e.g., **Daniel Hahn** shares drafts with living authors for comprehension checks while retaining English stylistic authority; routes formal inquiries through publisher/agent) vs. Autonomous (e.g., **Jennifer Croft** avoids consulting the author during active drafting so the translation grows as its own "living organism").

---

### 1.3 Core Translation Techniques & Seminal Books

| Work / Theorist | Core Practical Concept | Operational Takeaway for Craft |
| :--- | :--- | :--- |
| **Edith Grossman**, *Why Translation Matters* (2010) | Translation as critical interpretation & creative writing | Rejects mechanical equivalence; argues the translator writes the book the author *would have written* in the target language. |
| **Umberto Eco**, *Mouse or Rat? Translation as Negotiation* (2003) | Translation as **negotiation** of losses and gains | Every choice trades literal precision for intended effect ("saying almost the same thing"); loss in one spot justifies gain elsewhere. |
| **Lawrence Venuti**, *The Translator's Invisibility* (1995) | **Domestication** vs. **Foreignization** | *Domestication* erases foreignness for transparent fluency; *Foreignization* retains cultural/syntactic markers to "send the reader abroad" ethically. |
| **David Bellos**, *Is That a Fish in Your Ear?* (2011) | Pragmatic debunking of "literal" fidelity | Meaning is context- and register-dependent; "word-for-word" fidelity is an illusion. |
| **Mark Polizzotti**, *Sympathy for the Traitor* (2018) | Translator as creative partner, not traitor | Defends artistic latitude needed to make prose "sing" rather than stutter under literalist guilt. |
| **Mona Baker**, *In Other Words* (1992–2018) | Bottom-up equivalence & textual cohesion | Practical taxonomy for non-equivalence: generalization, cultural substitution, paraphrase, omission/addition; preserving collocations & thematic progression. |
| **Douglas Robinson**, *Becoming a Translator* (1997–2020) | Subliminal flow vs. analytical troubleshooting | Balances intuitive fast drafting ("abduction/induction") with conscious problem-solving when automaticity stalls. |
| **Vinay & Darbelnet** (1958) | **7 Translation Procedures** | *Direct:* (1) Borrowing, (2) Calque, (3) Literal. *Oblique:* (4) Transposition (POS shift), (5) Modulation (perspective shift), (6) Equivalence (idiom-for-idiom), (7) Adaptation (cultural reference swap). |
| **Peter Newmark** (1981/1988) | **Semantic vs. Communicative** translation; **Compensation** | *Compensation* offsets inevitable translation loss at point A by introducing an equivalent stylistic/tonal effect at point B. |
| **Katharina Reiss & Hans Vermeer** (1978/1984) | **Skopos Theory** | The target text's *purpose* (skopos) and audience govern strategy—overriding rigid source-text formalism. |

#### Micro-Techniques for Untranslatable Cruxes
* **Honorifics & Formality (T-V distinctions, `-san`/`oppa`/`tu`/`vous`):** Retention/borrowing (for familiar cultural genres), register compensation (polite syntax, titles like *Sir/Madam*), or strategic shifts between first-name and surname address.
* **Dialect & Sociolect:** Avoid mapping Source Region X onto Target Region Y (e.g., Cockney → Andalusian or Southern US), which creates jarring geographical anachronisms. Instead, use **slanted/general colloquialism** (non-standard syntax, contractions, class-neutral slang) + compensation. Neutralization to standard speech is a last resort.
* **Wordplay & Puns (Dirk Delabastita's taxonomy):** (1) *Pun → Pun* (inventing a new target pun fitting context), (2) *Pun → Non-Pun* (preserving literal sense + compensating nearby), (3) *Pun → Related Rhetorical Device* (alliteration, rhyme, irony), (4) *Zero translation / Footnote* (avoided in trade fiction).
* **Culture-Specific Items / Realia (Javier Franco Aixelá):** Conservation (borrowing), naturalization (orthographic adaptation), cultural substitution (risks breaking historical/geographical realism), or unobtrusive **inline glossing** (*"a bowl of matcha green tea"*).

---

## 2. The Technical & Operational Workflow (Tools, Artifacts, and Passes)

### 2.1 Concrete Working Artifacts & Exact Fields

1. **The Translator's Editorial Style Sheet (Project Bible)**
   - **Project Metadata:** Source/target language & locale (`en-US` vs `en-GB`), governing style manual (*Chicago Manual of Style*, *New Hart's Rules*), primary authoritative dictionary (*Merriam-Webster*, *Le Robert*, *Duden*).
   - **Character List & Cast:** `source_name`, `target_name / transliteration`, `aliases_epithets`, `titles_honorifics`, `pronouns_and_register` (e.g., `Sie/du`, `tu/vous`), `narrative_role / context`.
   - **Glossary & Recurring Motifs:** `source_term`, `approved_target_term`, `first_appearance_location`, `context_meaning`, `do_not_use_variants` (banned translations), `case_sensitivity` (e.g., capitalized magic/political terms mid-sentence).
   - **Spelling & Orthography Decisions:** Compound rules (open/hyphenated/closed), foreign loanword italicization rules (e.g., first use only vs. always), onomatopoeia/animal sounds, regional spelling locks (`-ize` vs. `-ise`).
   - **Punctuation & Dialogue Mechanics:** Dialogue markers (adapting Russian/Spanish em-dashes `—` or guillemets `«»` to curly quotes `“”`), interior monologue styling (italics vs. single quotes), spaced vs. unspaced em-dashes, ellipsis formatting, number/date spelling rules.
   - **Translator's Notes & Rationale:** Running explanations of intentional deviations, puns, or broken syntax for the publisher's copyeditor.

2. **Character & Relationship Matrix (Dyadic Register Grid)**
   - Maps not only individual **Voice Cards** (sentence length, sociolect, catchphrases, **negative constraints / words the character would never say**), but **directed edges between characters** (`Character A -> Character B`: formal vs. informal address, shifts across plot arcs—e.g., `vous` flipping to `tu` in Chapter 14).

3. **Timeline & Chronology Sheet**
   - Converts relative time markers (*"the next morning"*, *"three days later"*) into **absolute anchor points** (`Day 3 of Siege`, `Year 412`), alongside travel times and alibis, preventing tense-induced temporal contradictions.

4. **Decision Log (Delta Log)**
   - Chronological log of hard trade-offs (`Chapter/Page`, `Source Crux`, `Decision Taken`, `Rationale / Compensation Strategy`, `Retroactive Check Needed?`).

---

### 2.2 Tooling: CAT Tools vs. Word / Scrivener
* **Why Commercial/Technical Translators Use CAT Tools (memoQ, Trados Studio, OmegaT, CafeTran Espresso):**
  Built for repetitive manuals, legal contracts, and software localization where segment-level Translation Memory (TM) reuse and rigid terminology enforcement drive speed and consistency.
* **Why Many Literary Translators Avoid Strict Segment-by-Segment TM:**
  1. Grid/table UIs fracture prose rhythm and encourage sentence-for-sentence structural calquing rather than cross-sentence restructuring (splitting/merging sentences across paragraphs).
  2. Inline formatting tags disrupt creative immersion.
  3. TM fuzzy-matching is counterproductive when identical phrases carry different emotional/contextual weight across scenes.
* **Preferred Literary Environments:**
  - **Microsoft Word / LibreOffice:** Continuous-canvas drafting, comments pane for self-queries, track changes with editors, zero friction. (Some translators like **Ann Goldstein** also print physical paper drafts for layered pen editing.)
  - **Scrivener:** Widely favored as a "writer's environment" for books—chapter/scene **Binder**, **Research Tab** (storing source PDFs, maps, timelines, dictionaries in one file), **Split-Screen** (source on top/left, draft on bottom/right), and seamless manuscript compilation.
* **Which CAT Features ARE Actually Valuable for Book-Length Work:**
  - **Concordance Search (KWIC):** In **memoQ** (`Ctrl+K`, [docs.memoq.com](https://docs.memoq.com/current/en/Views/concordance-window.html)) or **CafeTran Espresso**, searching a word/motif across the entire manuscript to see how it was rendered 150 pages earlier—essential for structural motifs and character catchphrases.
  - **LiveDocs / Bilingual Alignment:** memoQ's **LiveDocs** ([docs.memoq.com](https://docs.memoq.com/current/en/Concepts/livedocs.html)) lets translators align existing translations, author glossaries, or reference corpora for instant lookup without polluting a strict TM.
  - **Termbase Highlighting:** Real-time pop-ups with rich usage notes (`"Use 'X' only when Y speaks"`) prevent character/place name drift across 80,000+ words (available in memoQ, CafeTran, and OmegaT's `/glossary` inflected matching, [omegat.org](https://omegat.org/documentation)).
  - **Automated QA Consistency Checks:** Catching **untranslated/skipped segments** (vital in long books), banned term variants, mismatched quotation/dash pairs, double spaces, and number/proper-noun discrepancies.

---

### 2.3 The Multi-Pass Workflow (Sequence & Variations)

1. **Pass 0 — Macro Prep (or Delayed Prep):** Read book (Grossman) or dive straight in (Rabassa/Hahn); seed initial Style Sheet, Glossary, and Character Matrix; conduct external/paratext research.
2. **Pass 1 — The Rough / "Hot" / "Vomit" Draft:**
   Prioritize narrative velocity and scene momentum. Accept temporary calques; insert bracketed placeholders (`[TK: pun on rain]`, `[CHECK: 19th-c. carriage part]`) rather than stalling.
   *(Notable collaborative variant: **Pevear & Volokhonsky** split Pass 1 and Pass 2 across two people—Volokhonsky produces a literal English draft + extensive philological notes; Pevear, without reading Russian, shapes it into idiomatic English; then they iterate back-and-forth against the Russian.)*
3. **Pass 2 — Comparative Bilingual Check (Accuracy & Fidelity Pass):**
   Line-by-line collation of target draft against source text. Catch dropped clauses, accidental additions, semantic drift, FID/tense flattening, and update the Style Sheet/Glossary with newly solved cruxes (retroactively propagating fixes to earlier chapters).
4. **Pass 3 — Monolingual "Blind Revision" + Reading Aloud (Flow Pass):**
   After a cooling-off gap (days/weeks), **hide/close the source text completely**. Read only the target manuscript—ideally **reading aloud** (emphasized by **Ros Schwartz**, etc.) to expose tongue-twisters, breathlessness, stiff dialogue, accidental internal rhymes, and "translationese." Any sentence incomprehensible without peeking at the source is rewritten from scratch.
   *(Note: Some translators flip Passes 2 and 3—doing Blind Revision immediately after Draft 1, then a final Comparative Check to ensure stylistic rewrites didn't introduce semantic drift. Both sequences are practiced; a final fidelity verification after heavy monolingual rewriting is critical.)*
5. **Pass 4 — Global Consistency & Mechanical QA Pass:**
   Cross-check full manuscript against Style Sheet, Character Matrix, and Termbase (using concordance search / regex / CAT QA checks) for spelling, punctuation, motifs, and formatting.
6. **Pass 5 — Publisher Editorial, Copyediting & Proofs:**
   Deliver manuscript + Style Sheet to commissioning editor/copyeditor; negotiate Track Changes & queries (per PEN America Model Contract & Society of Authors guidelines, publishers may not alter style without translator consent: [PEN Model Contract](https://pen.org/a-model-contract-for-literary-translations/), [SoA Contracts Guide](https://societyofauthors.org/guidance/industry/translator-publisher-contracts/)); review final page proofs; for non-fiction, verify footnotes/bibliography and compile/review the new target-language index.

---

## 3. Translating the Art into a Deterministic LLM Pipeline

To replicate professional book translation without "LLM translationese," context amnesia, or silent drift, each human artifact and pass maps into a **stateful, schema-driven multi-stage pipeline**:

### 3.1 Core Data Schemas (Deterministic State Store)

```json
// 1. BookStyleSheet (Global Contract)
{
  "locale": "en-US",
  "style_manual": "Chicago_18",
  "foreignization_level": "moderate",
  "tense_policy": "preserve_source_shifts",
  "dialogue_punctuation": {"open": "“", "close": "”", "interior_monologue": "italics"},
  "dash_style": "unspaced_em_dash",
  "loanword_italicization": "first_occurrence_only",
  "structural_motifs": [{"motif_id": "M01", "source_pattern": "...", "locked_target_phrase": "...", "preserve_repetition": true}]
}

// 2. CharacterVoiceCard & RelationshipEdge
{
  "character_id": "C_IVAN",
  "source_names": ["Иван Петрович", "Ваня"],
  "target_names": {"formal": "Ivan Petrovich", "diminutive": "Vanya"},
  "voice_profile": {"sentence_length": "clipped", "register": "working_class_slanted", "tics": ["drops auxiliary verbs"]},
  "forbidden_lexicon": ["indeed", "splendid", "perchance"],
  "dyadic_registers": [
    {"to_character": "C_ANNA", "chapter_range": [1, 12], "address": "formal_V", "honorific": "Madam"},
    {"to_character": "C_ANNA", "chapter_range": [13, 24], "address": "informal_T", "honorific": "none"}
  ]
}

// 3. GlossaryEntry (Termbase)
{
  "term_id": "T042",
  "source_term": "...",
  "approved_target": "...",
  "case_sensitive": true,
  "do_not_use": ["..."],
  "context_rule": "Only for imperial court scenes; otherwise use '...'"
}

// 4. DecisionLogEntry & TimelineAnchor
{
  "chapter": 4, "chunk_id": "ch04_p12",
  "crux_type": "pun|idiom|quote|realia",
  "source_excerpt": "...",
  "strategy": "Delabastita_Pun_to_Pun|Newmark_Compensation|Canonical_Quote_Lookup",
  "decision": "...",
  "retroactive_propagation_required": true
}
```

### 3.2 Retrieval & External Research Hooks (Pre-Draft & In-Flight)
1. **Full-Book Macro Ingestion (Pre-Pass 0):**
   - Run a two-level pass over the full source text (chapter summaries + entity/motif extraction + stylometric profiling: sentence-length distribution, tense transitions, FID candidate spans, recurring n-grams) to populate `BookStyleSheet`, `CharacterVoiceCard`, `RelationshipEdge`, `TimelineAnchor`, and `GlossaryEntry` *before* translating Chapter 1.
2. **Paratext & Critical Corpus Hook:**
   - Optional ingestion of source-language reviews, author interviews, existing translations (aligned via sentence-embeddings akin to memoQ LiveDocs), or fan-wiki lore into a read-only **Reference Corpus**.
3. **Canonical Quote & Citation Resolver (Non-Fiction & Literary Allusions):**
   - Detect quotation spans and named citations (`"..."`, blockquotes, footnotes). Before translating, query external retrieval (e.g., Google Books / Wikisource / Crossref / Wikipedia interlanguage links) to check whether a **canonical target-language original** exists; lock canonical quotes into the prompt as immutable constraints to eliminate back-translation errors.
4. **Dynamic Context & Concordance Injection (Per-Chunk):**
   - For each translation unit (prefer **multi-paragraph scenes or narrative beats** with overlapping context windows—never isolated sentences—to preserve cross-sentence rhythm and FID):
     - Inject only the *relevant subset* of `CharacterVoiceCard`s, active `RelationshipEdge`s (for the current chapter number), matching `GlossaryEntry` rules, `structural_motifs`, and **KWIC Concordance hits** from previously translated chapters (BM25 + embedding retrieval over `(source_chunk, target_chunk)` pairs).

### 3.3 Multi-Pass Deterministic State Machine

| State / Stage | Human Equivalent | LLM / Deterministic Execution Mechanics |
| :--- | :--- | :--- |
| **`S1_MACRO_ANALYSIS`** | Whole-book read & style sheet creation | Map-reduce over full book: extract cast, dyadic registers, timeline anchors, structural motifs, voice metrics, and candidate untranslatable cruxes. Optional **Human-in-the-Loop Gate** to approve Style Sheet / Glossary before drafting. |
| **`S2_RESEARCH_ENRICHMENT`** | Paratext, canonical quote & domain lookup | Resolve non-fiction citations, canonical target quotes, and Wikipedia/domain entity mappings; freeze immutable quote spans. |
| **`S3_HOT_DRAFT`** | Pass 1: Rough draft + `[TK]` placeholders | Translate scene-by-scene with injected Style Sheet/Voice Cards/Concordance. Instruct model to emit structured `[TK: type \| reason \| candidates]` tags for unresolvable puns/realia rather than hallucinating weak literalisms. Append new terms/decisions to `DecisionLog`. |
| **`S4_TK_RESOLUTION_&_PROPAGATION`** | Solving cruxes & retroactive consistency | Dedicated reasoning pass (or human escalation) resolves all `[TK]` tags using Vinay & Darbelnet / Delabastita / Compensation strategies, locks decisions into `GlossaryEntry`, and flags earlier chapters requiring retroactive updates. |
| **`S5_COMPARATIVE_FIDELITY`** | Pass 2: Bilingual check against source | Separate critic/verifier call receives `(source_scene, draft_scene, voice_cards, motif_list)` to audit semantic accuracy, omitted clauses, hallucinated additions, FID/tense preservation, and dyadic address shifts (`T/V`). Outputs structured diff edits. |
| **`S6_BLIND_CADENCE_POLISH`** | Pass 3: Blind revision & reading aloud | **Source text is deliberately withheld from the prompt.** Editor-persona LLM receives *only* the target scene + `BookStyleSheet` + `CharacterVoiceCard`s + prosody metrics (sentence-length variance, repeated-word proximity except locked motifs, dialogue naturalness). Rewrites clunky translationese/calques for target cadence. |
| **`S7_POST_POLISH_FIDELITY_GATE`** | Post-rewrite sanity check | Lightweight bilingual verification comparing `S5` vs `S6` against `source_scene` to guarantee the blind cadence polish (`S6`) did not introduce semantic drift, dropped facts, or broken motifs. (Loops back if drift > threshold.) |
| **`S8_GLOBAL_QA_&_COMPILE`** | Pass 4–5: CAT QA checks & final compile | Run deterministic code checks (no LLMs) before final export (EPUB/DOCX/LaTeX) + separate non-fiction index generator on final paginated text. |

### 3.4 Deterministic Automated QA Checks (Code-Level Gates in `S8`)
1. **Glossary & Negative-Constraint Scanner:** Exact/lemmatized regex checks verifying `approved_target` presence when `source_term` appears, zero occurrences of `do_not_use` or character `forbidden_lexicon` inside dialogue attributions.
2. **Omission / Addition & Length-Ratio Guard:** Sentence/paragraph alignment check verifying target chunks stay within calibrated length/sentence ratios relative to source.
3. **Entity, Number & Citation Bijection:** Deterministic extraction verifying all numbers, dates, footnote IDs, and untranslated/transliterated proper nouns match 1:1.
4. **Typography & Formatting Validator:** Balanced curly quotes, em-dash spacing, ellipsis format, italicization rules (loanwords italicized only on first appearance across the book), zero leftover `[TK]` markers.
5. **Motif Repetition Audit:** Verify `structural_motifs` with `preserve_repetition: true` were not silently replaced by synonyms during `S6_BLIND_CADENCE_POLISH`.

### 3.5 Critical LLM Failure Modes to Guard Against
* **"Synonym-itis" / Elegant Variation:** LLMs heavily penalize word repetition in English, destroying deliberate authorial leitmotifs → *Guard:* Lock motifs in `BookStyleSheet` and exempt them in `S6` + audit in `S8`.
* **FID & Tense Flattening:** LLMs normalize shifting literary tenses into uniform past tense and convert free indirect discourse into standard narrator exposition → *Guard:* Explicitly tag FID/tense-shift spans in `S1` and verify preservation in `S5`.
* **Blind-Polish Hallucination / Semantic Drift:** Withholding the source text in `S6` improves prose fluency but risks inventing details or softening sharp meanings → *Guard:* Mandatory `S7_POST_POLISH_FIDELITY_GATE` re-comparing against source.
* **Dialect Caricature:** Asking an LLM for "working-class" or "rural" speech often produces stereotypical caricatures → *Guard:* Constrain `CharacterVoiceCard` to *slanted colloquialism* (syntactic/contraction rules + forbidden caricatures).
* **Back-Translating Famous Quotes:** Translating a foreign version of a classic quote instead of restoring the original → *Guard:* `S2` canonical quote lookup + immutable span locking.
* **T-V / Honorific Drift Over Long Books:** Switching a pair from formal to informal randomly mid-book → *Guard:* Explicit `RelationshipEdge` with `chapter_range` injected per scene.

---

## 4. Key Authoritative Sources & References
* **PEN America — A Model Contract for Literary Translations:** https://pen.org/a-model-contract-for-literary-translations/
* **PEN America — Negotiating Contracts: A Translator's Checklist:** https://cdn.pen.org/wp-content/uploads/2024/09/22184919/translation_negotiators_checklist-1.pdf
* **CEATL — *New to Translation?* (Guide for Emerging Literary Translators):** https://guide.ceatl.eu/
* **CEATL — Guidelines for Fair Translation Contracts:** https://www.ceatl.eu/tools-of-the-trade/guidelines-for-fair-translations-contracts
* **The Society of Authors (Translators Association) — Overview & Resources:** https://societyofauthors.org/groups/translators-association/
* **The Society of Authors — Translator-Publisher Contracts Guide:** https://societyofauthors.org/guidance/industry/translator-publisher-contracts/
* **The Society of Authors — Translation Readers' Reports Best Practice Guidelines:** https://societyofauthors.org/guidance/industry/translation-readers-reports-best-practice-guidelines/
* **American Translators Association (ATA) — *Breaking Into Book Translation*:** https://www.atanet.org/blog/breaking-into-book-translation/
* **memoQ Documentation — Concordance Window:** https://docs.memoq.com/current/en/Views/concordance-window.html
* **memoQ Documentation — LiveDocs:** https://docs.memoq.com/current/en/Concepts/livedocs.html
* **OmegaT Official Documentation:** https://omegat.org/documentation
* **ACL Anthology — Kristiina Taivalkoski-Shilov (2019), *"Free indirect discourse: an insurmountable challenge for literary MT systems?"*:** https://aclanthology.org/W19-7305/
* **The Guardian — Edith Grossman Interview:** https://www.theguardian.com/books/2014/apr/26/gabriel-garcia-marquez-edith-grossman-interview
* **The Guardian — Edith Grossman Obituary:** https://www.theguardian.com/books/2023/sep/14/edith-grossman-obituary
