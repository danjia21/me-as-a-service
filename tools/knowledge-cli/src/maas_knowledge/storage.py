"""Small, atomic filesystem persistence helpers for instance-local artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


def canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def checksum_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{checksum_bytes(canonical_json(value))[:16]}"


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def load_structured[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ValueError(f"{path}: file does not exist") from error
    try:
        raw = (
            json.loads(text)
            if path.suffix.casefold() == ".json"
            else yaml.safe_load(text)
        )
        return model.model_validate(raw)
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"{path}: {error}") from error
