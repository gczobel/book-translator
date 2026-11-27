"""What a passage is given besides its text: the bible slice that concerns it and a concordance."""

import re
from dataclasses import dataclass

from book_translator.bible import AddressRule, Bible


@dataclass(frozen=True)
class SourceBlock:
    id: str
    chapter: int  # 0-based
    text: str


def _mentions(text: str, term: str) -> bool:
    return bool(term) and re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE) is not None


def _in_range(rule: AddressRule, chapter: int) -> bool:
    number = chapter + 1
    return (rule.from_chapter or 1) <= number <= (rule.to_chapter or number)


def bible_slice(bible: Bible, text: str, chapter: int, block_ids: list[str]) -> str:
    """The profile and style sheet, plus the cast, voice cards, address rules, glossary entries,
    motifs and predicted cruxes that this passage and its context touch."""
    cast = {m.name for m in bible.cast if any(_mentions(text, n) for n in (m.name, *m.aliases))}
    relevant = bible.model_copy(
        update={
            "cast": [m for m in bible.cast if m.name in cast],
            "voice_cards": [v for v in bible.voice_cards if v.character in cast],
            "address_grid": [
                r
                for r in bible.address_grid
                if _in_range(r, chapter) and {r.speaker, r.addressee} <= cast
            ],
            "glossary": [g for g in bible.glossary if _mentions(text, g.term)],
            "motifs": [m for m in bible.motifs if _mentions(text, m.name)],
            "summaries": [s for s in bible.summaries if s.chapter == chapter + 1],
            "timeline": [],
            "cruxes": [c for c in bible.cruxes if any(i in c.location for i in block_ids)],
        }
    )
    return relevant.model_dump_json()


def concordance(
    bible: Bible,
    text: str,
    chapter: int,
    earlier: list[tuple[SourceBlock, str]],
    limit: int = 3,
) -> list[dict[str, object]]:
    """For each glossary term or motif in the passage, the latest earlier-chapter blocks that
    carry it, with the target text they were given."""
    terms = [(g.term, g.rendering) for g in bible.glossary]
    terms += [(m.name, m.locked_rendering) for m in bible.motifs]
    out: list[dict[str, object]] = []
    for term, rendering in terms:
        if not _mentions(text, term):
            continue
        seen = [
            {"source": block.id, "target": target}
            for block, target in earlier
            if block.chapter < chapter and _mentions(block.text, term)
        ][-limit:]
        if seen:
            out.append({"term": term, "rendering": rendering, "earlier": seen})
    return out
