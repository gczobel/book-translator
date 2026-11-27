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


class Bible(BaseModel):
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
        return self
