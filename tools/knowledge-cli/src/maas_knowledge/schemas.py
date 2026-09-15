"""Validated contracts for an initialized instance and live retrieval index."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

SCHEMA_VERSION: Literal[1] = 1
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{7,63}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeBaseConfig(StrictModel):
    index: Literal["index/records.json"] = "index/records.json"


class InstanceLinks(StrictModel):
    public_profile: AnyHttpUrl | None = None
    repository: AnyHttpUrl | None = None


class InstanceManifest(StrictModel):
    """Instance presentation and live-index configuration."""

    display_name: str = Field(min_length=1)
    representation_label: str = Field(min_length=1)
    disclosure: str = Field(min_length=1)
    welcome_message: str = Field(min_length=1)
    knowledge_base: KnowledgeBaseConfig = Field(default_factory=KnowledgeBaseConfig)
    suggested_questions: tuple[str, ...] = Field(min_length=1)
    links: InstanceLinks = Field(default_factory=InstanceLinks)

    @field_validator(
        "display_name",
        "representation_label",
        "disclosure",
        "welcome_message",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("suggested_questions")
    @classmethod
    def normalize_questions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("suggested questions must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("suggested questions must be unique")
        return normalized


class ResumeMetadata(StrictModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    source_id: Identifier
    original_filename: str = Field(min_length=1)
    media_type: Literal["application/pdf", "text/markdown"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RetrievalRecord(StrictModel):
    """One complete, directly searchable unit of knowledge."""

    id: Identifier
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    url: AnyHttpUrl | None = None


class RetrievalRecordDraft(StrictModel):
    """A record supplied by the skill; the CLI creates an ID when omitted."""

    id: Identifier | None = None
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    url: AnyHttpUrl | None = None


class IndexUpdate(StrictModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    records: tuple[RetrievalRecordDraft, ...] = Field(min_length=1)
