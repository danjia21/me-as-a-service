import os
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from me_as_a_service.chat.prompts import load_prompts

REPOSITORY_ROOT = Path(__file__).parents[4]
DEFAULT_INSTANCE_DIR = Path("examples/fictional-profile")


class KnowledgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _validate_relative_path(value)


class EvaluationsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    questions: str

    @field_validator("questions")
    @classmethod
    def validate_questions(cls, value: str) -> str:
        return _validate_relative_path(value)


class LinksConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    public_profile: str | None = None
    repository: str | None = None


class RoutingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    personal_terms: tuple[str, ...] = Field(min_length=1)

    @field_validator("personal_terms")
    @classmethod
    def validate_terms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip().casefold() for value in values)
        if any(not value for value in normalized):
            raise ValueError("routing terms must not be blank")
        return normalized


class InstanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str = Field(min_length=1)
    representation_label: str = Field(min_length=1)
    disclosure: str = Field(min_length=1)
    knowledge: KnowledgeConfig
    evaluations: EvaluationsConfig | None = None
    suggested_questions: tuple[str, ...] = ()
    links: LinksConfig = LinksConfig()
    routing: RoutingConfig

    @field_validator("suggested_questions")
    @classmethod
    def validate_questions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("suggested questions must not be blank")
        return normalized


class Instance:
    def __init__(self, directory: Path, config: InstanceConfig) -> None:
        self.directory = directory
        self.config = config

    @property
    def knowledge_directory(self) -> Path:
        return self.resolve(self.config.knowledge.path)

    @property
    def evaluation_questions(self) -> Path | None:
        if self.config.evaluations is None:
            return None
        return self.resolve(self.config.evaluations.questions)

    @property
    def system_policy(self) -> str:
        return load_prompts().system_policy(self.config.display_name)

    def resolve(self, relative_path: str) -> Path:
        candidate = (self.directory / relative_path).resolve()
        if not candidate.is_relative_to(self.directory):
            raise ValueError("instance path escapes the instance directory")
        return candidate


def load_instance(directory: Path) -> Instance:
    resolved_directory = directory.resolve()
    manifest_path = resolved_directory / "instance.yaml"
    raw_config = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    config = InstanceConfig.model_validate(raw_config)
    instance = Instance(resolved_directory, config)
    if not instance.knowledge_directory.is_dir():
        raise ValueError("instance knowledge path must be a directory")
    _ = instance.evaluation_questions
    return instance


def load_selected_instance() -> Instance:
    configured_path = Path(os.getenv("MAAS_INSTANCE_DIR", str(DEFAULT_INSTANCE_DIR)))
    if not configured_path.is_absolute():
        configured_path = REPOSITORY_ROOT / configured_path
    return load_instance(configured_path)


def _validate_relative_path(value: str) -> str:
    normalized = value.strip()
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError(
            "instance paths must be relative and remain inside the instance"
        )
    return normalized
