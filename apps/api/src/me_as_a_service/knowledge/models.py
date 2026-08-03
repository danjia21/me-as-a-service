from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

KnowledgeScope = Literal["resume", "personal", "public"]


class FurtherReading(BaseModel):
    """A labeled external link a passage's source document points readers to."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1)
    url: str = Field(min_length=1)


class Passage(BaseModel):
    """A citable, ordered unit of text derived from one source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passage_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_title: str = ""
    section_path: tuple[str, ...]
    query_hints: tuple[str, ...] = ()
    text: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    further_reading: tuple[FurtherReading, ...] = ()


class SourceDocument(BaseModel):
    """A validated source plus the passages deterministically derived from it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    scope: KnowledgeScope
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    passages: tuple[Passage, ...]
