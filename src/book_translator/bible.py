"""The book bible: one schema object that the whole pipeline reads.

Part 1 (profile, style sheet, cast, voice cards) is built by the whole-book consolidation.
Part 2 (address grid, glossary, motifs, summaries, timeline, cruxes) is added as further
fields with defaults, so a stored part-1 bible keeps validating.
"""

from typing import Literal, Self

from pydantic import BaseModel, model_validator


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
    dialogue: Literal["raya-split", "inline-quotes"] = "raya-split"
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
    form: Literal["tú", "usted"]
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
    origin: Literal["extracted", "researched", "established"]
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

    type: Literal["pun", "lyrics", "quotation", "dialect"]
    location: str
    note: str = ""
    # For a quoted song, poem or scripture: use a published translation (named in `source`) or
    # render it ourselves, in which case the rendering is marked as ours.
    recommendation: Literal["existing translation", "our own"] | None = None
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

    @model_validator(mode="after")
    def _voice_cards_belong_to_the_cast(self) -> Self:
        names = {m.name for m in self.cast}
        unknown = [v.character for v in self.voice_cards if v.character not in names]
        if unknown:
            raise ValueError(f"voice cards for characters outside the cast: {unknown}")
        self.check_against_cast(names)
        return self
