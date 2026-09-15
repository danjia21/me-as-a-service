"""Resolve paths for one selected application instance."""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import cast

import yaml

REPOSITORY_ROOT = Path(__file__).parents[4]
DEFAULT_INSTANCE_DIR = Path("instance/example")
EVALUATION_QUESTIONS_RELATIVE_PATH = Path("evaluations/evidence_required.json")


@dataclass(frozen=True, slots=True)
class Instance:
    """Paths and loaded data belonging to one application instance."""

    directory: Path
    _manifest: Mapping[str, object] = field(init=False, repr=False)
    _records: tuple[object, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "directory", self.directory.resolve())
        object.__setattr__(self, "_manifest", _load_manifest(self.manifest_path))
        object.__setattr__(self, "_records", _load_records(self.index_path))

    @property
    def manifest_path(self) -> Path:
        return self.directory / "instance.yaml"

    @property
    def index_path(self) -> Path:
        return self.directory / "index" / "records.json"

    @property
    def evaluation_questions_path(self) -> Path:
        return self.directory / EVALUATION_QUESTIONS_RELATIVE_PATH

    @property
    def manifest(self) -> Mapping[str, object]:
        return self._manifest

    @property
    def records(self) -> tuple[object, ...]:
        return self._records

    @property
    def display_name(self) -> str:
        value = self.manifest.get("display_name")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                "instance manifest field 'display_name' must be a non-blank string"
            )
        return value.strip()

    @property
    def public_profile(self) -> str | None:
        """Return the curated public-profile URL when one is configured."""

        links = self.manifest.get("links")
        if not isinstance(links, Mapping):
            return None
        value = links.get("public_profile")
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip()

    def evaluation_questions(self) -> dict[str, str]:
        """Load and validate this instance's evidence-required questions."""

        return _load_evaluation_questions(self.evaluation_questions_path)


def load_instance(directory: Path) -> Instance:
    """Return an instance rooted at an absolute, normalized directory."""

    return Instance(directory.resolve())


def load_instance_from_environment() -> Instance:
    """Return the instance selected by the environment."""

    configured_path = Path(os.getenv("MAAS_INSTANCE_DIR", str(DEFAULT_INSTANCE_DIR)))
    if not configured_path.is_absolute():
        configured_path = REPOSITORY_ROOT / configured_path
    return load_instance(configured_path)


def _load_manifest(path: Path) -> Mapping[str, object]:
    try:
        raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"instance manifest does not exist: {path}") from error
    except OSError as error:
        raise ValueError(f"instance manifest is unreadable: {path}") from error
    except yaml.YAMLError as error:
        raise ValueError(
            f"instance manifest is invalid YAML: {path}: {error}"
        ) from error

    if not isinstance(raw, Mapping):
        raise ValueError("instance manifest must be an object")
    if not all(isinstance(key, str) for key in raw):
        raise ValueError("instance manifest field names must be strings")
    return MappingProxyType(dict(cast(Mapping[str, object], raw)))


def _load_records(path: Path) -> tuple[object, ...]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"instance records do not exist: {path}") from error
    except OSError as error:
        raise ValueError(f"instance records are unreadable: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(
            f"instance records are invalid JSON: {path}: {error}"
        ) from error

    if not isinstance(raw, list):
        raise ValueError("instance records must be a JSON array")
    return tuple(raw)


def _load_evaluation_questions(path: Path) -> dict[str, str]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"evaluation questions do not exist: {path}") from error
    except OSError as error:
        raise ValueError(f"evaluation questions are unreadable: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(
            f"evaluation questions are invalid JSON: {path}: {error}"
        ) from error

    if not isinstance(raw, list):
        raise ValueError("evaluation questions must be a JSON array")

    entries = tuple(
        _parse_evaluation_question(value, index=index)
        for index, value in enumerate(raw)
    )
    ids = [question_id for question_id, _ in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("evaluation question IDs must be unique")
    normalized_questions = [question.casefold() for _, question in entries]
    if len(normalized_questions) != len(set(normalized_questions)):
        raise ValueError("evaluation questions must be unique")
    return dict(entries)


def _parse_evaluation_question(value: object, *, index: int) -> tuple[str, str]:
    location = f"evaluation question {index}"
    if not isinstance(value, Mapping):
        raise ValueError(f"{location} must be an object")
    if not all(isinstance(field, str) for field in value):
        raise ValueError(f"{location} field names must be strings")
    question = cast(Mapping[str, object], value)

    expected_fields = {"id", "question"}
    if set(question) != expected_fields:
        raise ValueError(f"{location} must contain exactly {sorted(expected_fields)}")

    question_id = cast(str, question["id"])
    question_text = cast(str, question["question"])

    return question_id.strip(), question_text.strip()
