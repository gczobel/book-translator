"""The QA checks on their own: what counts as the bible's rendering, and what is a name."""

from book_translator.bible import Bible, CastMember, GlossaryEntry, Motif
from book_translator.inline import EncodedBlock
from book_translator.qa import QAContext, banned_variants, glossary_renderings, motifs, names


def context(
    source: str,
    target: str,
    *,
    glossary: list[GlossaryEntry] | None = None,
    motif: list[Motif] | None = None,
    cast: list[CastMember] | None = None,
    book: str = "",
) -> QAContext:
    bible = Bible.model_construct(glossary=glossary or [], motifs=motif or [], cast=cast or [])
    sources = {"b#0": EncodedBlock(source, {})}
    if book:  # the rest of the book, as one more block
        sources["b#1"] = EncodedBlock(book, {})
    return QAContext(sources=sources, targets={"b#0": [target], "b#1": [book]}, bible=bible)


def entry(term: str, rendering: str) -> GlossaryEntry:
    return GlossaryEntry(term=term, rendering=rendering, origin="established")


def test_any_alternative_of_a_rendering_written_with_a_slash_is_accepted() -> None:
    glossary = [
        entry("American Minister", "el ministro norteamericano / el ministro de los EE. UU.")
    ]
    ok = context(
        "The American Minister came.", "El ministro de los EE. UU. llegó.", glossary=glossary
    )
    bad = context("The American Minister came.", "El embajador llegó.", glossary=glossary)

    assert glossary_renderings(ok) == []
    assert len(glossary_renderings(bad)) == 1


def test_a_note_in_brackets_after_a_rendering_is_not_part_of_it() -> None:
    glossary = [entry("phantasmata", "phantasmata (cursiva)")]

    assert (
        glossary_renderings(context("The phantasmata.", "Los phantasmata.", glossary=glossary))
        == []
    )


def test_a_rendering_with_the_article_el_is_met_by_al_and_del() -> None:
    glossary = [entry("the Garden of Death", "el Jardín de la Muerte")]
    for target in ("Se refiere al Jardín de la Muerte.", "Las flores del Jardín de la Muerte."):
        found = glossary_renderings(context("The Garden of Death.", target, glossary=glossary))

        assert found == []


def test_a_locked_motif_accepts_any_of_its_alternatives_and_the_contracted_article() -> None:
    moon = [Motif(name="Moonlight", locked_rendering="la luna / rayo de luna")]
    garden = [Motif(name="The Garden of Death", locked_rendering="el Jardín de la Muerte")]

    assert motifs(context("Moonlight.", "A la luz del rayo de luna.", motif=moon)) == []
    assert motifs(context("The Garden of Death.", "Al Jardín de la Muerte.", motif=garden)) == []
    assert len(motifs(context("Moonlight.", "A la luz del sol.", motif=moon))) == 1


MARY = [
    CastMember(name="Mary Tudor", aliases=["Mary", "the Queen"], gender="female", role="a queen")
]


def test_only_the_names_of_the_cast_are_checked() -> None:
    plain_words = context(
        "Then I met the American Minister in London.", "Luego conocí al ministro."
    )

    assert names(plain_words) == []
    assert names(context("Then I met the Minister.", "Luego.", cast=MARY)) == []


def test_a_description_a_single_letter_and_an_honorific_are_not_names() -> None:
    cast = [
        CastMember(
            name="Mr. Hiram B. Otis", aliases=["the American Minister"], gender="male", role="x"
        )
    ]
    source = "Then Mr. Otis saw B the American Minister."

    assert [f.message for f in names(context(source, "Luego vio al ministro.", cast=cast))] == [
        "the name 'Otis' is not in the target"
    ]


def test_a_title_in_a_cast_name_has_a_spanish_word_of_its_own() -> None:
    cast = [CastMember(name="Duke of Cheshire", aliases=["Mr. Ghost"], gender="m", role="x")]
    source = "Then the Duke and the Ghost met Cheshire."

    assert [
        f.message for f in names(context(source, "Luego el duque y el fantasma.", cast=cast))
    ] == ["the name 'Cheshire' is not in the target"]


def test_a_cast_name_matches_without_regard_to_accents_or_a_plural_s() -> None:
    cast = [CastMember(name="Paris Hilton", aliases=[], gender="f", role="x")]
    plural = [CastMember(name="Canterville", aliases=[], gender="m", role="x")]

    assert names(context("He met Paris Hilton.", "Conoció a París Hilton.", cast=cast)) == []
    assert names(context("The Cantervilles left.", "Los Canterville.", cast=plural)) == []


def test_a_cast_name_missing_from_the_target_is_still_a_finding() -> None:
    found = names(context("Then Mary left.", "Entonces se fue.", cast=MARY))

    assert [f.message for f in found] == ["the name 'Mary' is not in the target"]


def test_a_banned_variant_is_a_finding_only_where_the_source_uses_the_term() -> None:
    glossary = [
        GlossaryEntry(
            term="phantasmata",
            rendering="phantasmata",
            banned_variants=["fantasmas"],
            origin="established",
        )
    ]
    elsewhere = context("Ghosts are old.", "Los fantasmas son viejos.", glossary=glossary)
    there = context("The phantasmata.", "Los fantasmas.", glossary=glossary)

    assert banned_variants(elsewhere) == []
    assert len(banned_variants(there)) == 1
