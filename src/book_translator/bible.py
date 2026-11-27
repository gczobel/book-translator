"""The book bible: one schema object that the whole pipeline reads.

Part 1 (profile, style sheet, cast, voice cards) is built by the whole-book consolidation.
Part 2 (address grid, glossary, motifs, summaries, timeline, cruxes) is added as further
fields with defaults, so a stored part-1 bible keeps validating.
"""

from collections.abc import Iterable
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, BeforeValidator, model_validator

from book_translator.tolerance import choice, plain


def settle_names(data: Any, cast: Iterable[tuple[str, Iterable[str]]]) -> Any:
    """Rewrite the character names a model used for the cast's own spelling (by name or alias,
    ignoring case, accents and punctuation). A name that matches nobody is left for the
    validators to reject."""
    if not isinstance(data, dict):
        return data
    known: dict[str, str] = {}
    for name, aliases in cast:
        for spelling in (name, *aliases):
            known.setdefault(plain(spelling), name)

    def settle(value: Any) -> Any:
        return known.get(plain(value), value) if isinstance(value, str) else value

    data = dict(data)
    for field, keys in (
        ("voice_cards", ("character",)),
        ("address_grid", ("speaker", "addressee")),
    ):
        rows = data.get(field)
        if isinstance(rows, list):
            data[field] = [
                {**row, **{k: settle(row.get(k)) for k in keys if k in row}}
                if isinstance(row, dict)
                else row
                for row in rows
            ]
    return data


def cast_of(data: Any) -> list[tuple[str, list[str]]]:
    members = data.get("cast") if isinstance(data, dict) else None
    return [
        (m["name"], [a for a in m.get("aliases", []) if isinstance(a, str)])
        for m in members or []
        if isinstance(m, dict) and isinstance(m.get("name"), str)
    ]


class Profile(BaseModel):
    genre: str
    period: str
    setting: str
    narrator: str
    narrator_distance: str
    tense: str
    narrative_register: str
    foreignness: str  # how foreign the translation should feel


class StyleSheet(BaseModel):
    dialogue: Annotated[
        Literal["raya-split", "inline-quotes"],
        BeforeValidator(choice("raya-split", "inline-quotes")),
    ] = "raya-split"
    thoughts: str
    numbers: str
    titles: str


class CastMember(BaseModel):
    name: str
    aliases: list[str] = []
    gender: str
    role: str


class VoiceCard(BaseModel):
    character: str  # a cast member's name
    speech_register: str
    tics: list[str] = []
    never_says: list[str] = []
    sample_lines: list[str] = []


class AddressRule(BaseModel):
    """How one character addresses another (directed), over a range of chapters (1-based,
    inclusive, open-ended when absent)."""

    speaker: str
    addressee: str
    form: Annotated[Literal["tú", "usted"], BeforeValidator(choice("tú", "usted"))]
    from_chapter: int | None = None
    to_chapter: int | None = None

    @model_validator(mode="after")
    def _range_runs_forwards(self) -> Self:
        if (
            self.from_chapter is not None
            and self.to_chapter is not None
            and self.from_chapter > self.to_chapter
        ):
            raise ValueError(f"chapter range {self.from_chapter}-{self.to_chapter} runs backwards")
        return self


class GlossaryEntry(BaseModel):
    term: str
    rendering: str
    banned_variants: list[str] = []
    context_rule: str = ""
    origin: Annotated[
        Literal["extracted", "researched", "established"],
        BeforeValidator(choice("extracted", "researched", "established")),
    ]
    source: str = ""  # where an established rendering was found


class Motif(BaseModel):
    name: str
    locked_rendering: str
    description: str = ""


class ChapterSummary(BaseModel):
    chapter: int  # 1-based
    summary: str


class TimelineEvent(BaseModel):
    when: str
    event: str
    chapter: int | None = None


class Crux(BaseModel):
    """A passage predicted to need a decision: where the translation is likely to get stuck."""

    type: Annotated[
        Literal["pun", "lyrics", "quotation", "dialect"],
        BeforeValidator(choice("pun", "lyrics", "quotation", "dialect")),
    ]
    location: str
    note: str = ""
    # For a quoted song, poem or scripture: use a published translation (named in `source`) or
    # render it ourselves, in which case the rendering is marked as ours.
    recommendation: (
        Annotated[
            Literal["existing translation", "our own"],
            BeforeValidator(choice("existing translation", "our own")),
        ]
        | None
    ) = None
    source: str = ""


class Part2(BaseModel):
    """The second half of the bible, written once part 1 is known."""

    address_grid: list[AddressRule] = []
    glossary: list[GlossaryEntry] = []
    motifs: list[Motif] = []
    summaries: list[ChapterSummary] = []
    timeline: list[TimelineEvent] = []
    cruxes: list[Crux] = []

    def check_against_cast(self, names: set[str]) -> None:
        unknown = sorted(
            {n for r in self.address_grid for n in (r.speaker, r.addressee) if n not in names}
        )
        if unknown:
            raise ValueError(f"address rules for characters outside the cast: {unknown}")


class Bible(Part2):
    profile: Profile
    style: StyleSheet
    cast: list[CastMember]
    voice_cards: list[VoiceCard] = []

    @model_validator(mode="before")
    @classmethod
    def _names_as_in_the_cast(cls, data: Any) -> Any:
        return settle_names(data, cast_of(data))

    @model_validator(mode="after")
    def _voice_cards_belong_to_the_cast(self) -> Self:
        names = {m.name for m in self.cast}
        unknown = [v.character for v in self.voice_cards if v.character not in names]
        if unknown:
            raise ValueError(f"voice cards for characters outside the cast: {unknown}")
        self.check_against_cast(names)
        return self
