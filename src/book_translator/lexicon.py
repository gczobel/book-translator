"""The variety lexicon: a small curated list of words typical of one Spanish variety.

Each list holds words (and the inflected forms that matter) that give a variety away, so a
translation meant for another variety can be checked for them. It is deliberately small: a word
joins only if it is rare outside its variety and not an ordinary word elsewhere (`sos`, `vale`
and a bare `vos` stay out: SOS, the verb *valer* and archaic *vos* would raise false alarms).
`variety_words` is the lookup the `variety` QA check uses; the workspace `variety` setting
(`peninsular`, `rioplatense` or `neutral`, i.e. Latin American neutral) picks which lists are
foreign to it.
"""

from book_translator.qa import Finding, QAContext, check, contains, target_text

PENINSULAR = frozenset(
    "coger coge cogen cogemos cogéis cogí cogiste cogió cogieron cogiendo cojan "
    "ordenador ordenadores móvil móviles vosotros vosotras vuestro vuestra vuestros vuestras "
    "habéis estáis tenéis sois queréis podéis zumo zumos patata patatas guay chaval chavales "
    "aparcar".split()
)

RIOPLATENSE = frozenset(
    "tenés querés podés sabés hacés andás mirá vení decime hacé "
    "che pibe pibes boludo boluda laburo laburar bondi heladera frutilla pollera nafta "
    "remera".split()
)

# Used across Latin America, the River Plate included: foreign only to a peninsular text.
LATIN_AMERICAN = frozenset("computadora computadoras celular celulares".split())

# Regional to Mexico and the north of Latin America: foreign to peninsular and River Plate texts.
AMERICAN_REGIONAL = frozenset(
    "platicar platicó platiqué platicaron platicando ahorita chamba chévere".split()
)

FOREIGN_TO: dict[str, tuple[frozenset[str], ...]] = {
    "peninsular": (RIOPLATENSE, LATIN_AMERICAN, AMERICAN_REGIONAL),
    "rioplatense": (PENINSULAR, AMERICAN_REGIONAL),
    "neutral": (PENINSULAR, RIOPLATENSE),
}


def variety_words(variety: str) -> list[str]:
    """The words typical of some other variety, which a text in `variety` should not use."""
    return sorted(word for words in FOREIGN_TO.get(variety, ()) for word in words)


@check("variety")
def variety_lexicon(context: QAContext) -> list[Finding]:
    """A target block using a word typical of another Spanish variety than the workspace's."""
    words = variety_words(context.variety)
    return [
        Finding("variety", block, f"{word!r} is not {context.variety} Spanish")
        for block in context.targets
        for word in words
        if contains(target_text(context, block), word)
    ]
