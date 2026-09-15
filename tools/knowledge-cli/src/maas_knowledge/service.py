"""Small, atomic service for creating and enriching a live retrieval index."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml
from pydantic import AnyHttpUrl, TypeAdapter
from pypdf import PdfReader

from maas_knowledge.schemas import (
    IndexUpdate,
    InstanceManifest,
    ResumeMetadata,
    RetrievalRecord,
    RetrievalRecordDraft,
)
from maas_knowledge.storage import (
    atomic_write,
    checksum_bytes,
    load_structured,
    stable_id,
)

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid"}
RECORD_LIST = TypeAdapter(list[RetrievalRecord])


class KnowledgeInitializer:
    """Operate on one explicitly selected instance directory."""

    def __init__(self, instance: Path) -> None:
        self.instance = instance.resolve()
        self.resume_dir = self.instance / "inputs" / "resume"
        self.index_path = self.instance / "index" / "records.json"
        self.manifest_path = self.instance / "instance.yaml"

    def initialize(self) -> dict[str, Any]:
        self.resume_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_manifest()
        if not self.index_path.exists():
            self._write_index(())
        return self.status()

    def status(self) -> dict[str, Any]:
        records = self.records() if self.index_path.exists() else ()
        metadata_path = self.resume_dir / "metadata.json"
        return {
            "instance": str(self.instance),
            "resume_imported": metadata_path.exists(),
            "index_present": self.index_path.exists(),
            "record_count": len(records),
        }

    def import_resume(self, resume: Path) -> ResumeMetadata:
        self.initialize()
        resume = resume.resolve()
        suffix = resume.suffix.casefold()
        if suffix not in {".pdf", ".md", ".markdown"}:
            raise ValueError(f"{resume}: resume must be PDF or Markdown")
        original = resume.read_bytes()
        media_type: Literal["application/pdf", "text/markdown"] = (
            "application/pdf" if suffix == ".pdf" else "text/markdown"
        )
        normalized = (
            self._normalize_pdf(resume)
            if suffix == ".pdf"
            else self._normalize_markdown(original)
        )
        metadata = ResumeMetadata(
            source_id=stable_id("resume", {"sha256": checksum_bytes(original)}),
            original_filename=resume.name,
            media_type=media_type,
            sha256=checksum_bytes(original),
            normalized_sha256=checksum_bytes(normalized.encode("utf-8")),
        )
        metadata_path = self.resume_dir / "metadata.json"
        if metadata_path.exists():
            existing = ResumeMetadata.model_validate_json(
                metadata_path.read_text(encoding="utf-8")
            )
            if existing == metadata:
                return existing
        atomic_write(self.resume_dir / "original", original)
        atomic_write(self.resume_dir / "normalized.md", normalized.encode("utf-8"))
        atomic_write(
            metadata_path,
            json.dumps(
                metadata.model_dump(mode="json"),
                indent=2,
                ensure_ascii=False,
            ).encode("utf-8")
            + b"\n",
        )
        return metadata

    def records(self) -> tuple[RetrievalRecord, ...]:
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ValueError(f"{self.index_path}: file does not exist") from error
        except json.JSONDecodeError as error:
            raise ValueError(f"{self.index_path}: {error}") from error
        try:
            records = tuple(RECORD_LIST.validate_python(raw))
        except ValueError as error:
            raise ValueError(f"{self.index_path}: {error}") from error
        self._validate_records(records)
        return records

    def replace_index(self, proposal_path: Path) -> dict[str, Any]:
        proposal = load_structured(proposal_path, IndexUpdate)
        records = self._materialize(proposal.records)
        self._write_index(records)
        return self._index_result(records, changed_ids=tuple(r.id for r in records))

    def upsert_index(self, proposal_path: Path) -> dict[str, Any]:
        proposal = load_structured(proposal_path, IndexUpdate)
        updates = self._materialize(proposal.records)
        merged = {record.id: record for record in self.records()}
        merged.update({record.id: record for record in updates})
        records = tuple(sorted(merged.values(), key=lambda record: record.id))
        self._validate_records(records)
        self._write_index(records)
        return self._index_result(records, changed_ids=tuple(r.id for r in updates))

    def remove_records(self, record_ids: tuple[str, ...]) -> dict[str, Any]:
        if not record_ids:
            raise ValueError("at least one record ID is required")
        existing = self.records()
        known = {record.id for record in existing}
        unknown = set(record_ids) - known
        if unknown:
            raise ValueError(f"unknown record IDs: {sorted(unknown)}")
        removed = set(record_ids)
        records = tuple(record for record in existing if record.id not in removed)
        self._write_index(records)
        return self._index_result(records, changed_ids=tuple(sorted(removed)))

    def validate(self) -> dict[str, Any]:
        self._read_manifest()
        records = self.records()
        return self._index_result(records, changed_ids=()) | {"valid": True}

    def _ensure_manifest(self) -> InstanceManifest:
        if not self.manifest_path.exists():
            default = self._default_manifest()
            self._write_manifest(default)
            return default

        try:
            raw = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise ValueError(f"{self.manifest_path}: {error}") from error
        if not isinstance(raw, dict):
            raise ValueError(f"{self.manifest_path}: manifest must be an object")

        default = self._default_manifest()
        changed = False
        for obsolete_key in ("schema_version", "id"):
            if obsolete_key in raw:
                del raw[obsolete_key]
                changed = True
        defaults = default.model_dump(mode="json", exclude_none=True)
        for key in (
            "display_name",
            "representation_label",
            "disclosure",
            "welcome_message",
            "knowledge_base",
            "suggested_questions",
            "links",
        ):
            if key not in raw:
                raw[key] = defaults[key]
                changed = True
        try:
            manifest = InstanceManifest.model_validate(raw)
        except ValueError as error:
            raise ValueError(f"{self.manifest_path}: {error}") from error
        if changed:
            self._write_manifest(manifest)
        return manifest

    def _read_manifest(self) -> InstanceManifest:
        try:
            raw = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8"))
            return InstanceManifest.model_validate(raw)
        except FileNotFoundError as error:
            raise ValueError(f"{self.manifest_path}: file does not exist") from error
        except (yaml.YAMLError, ValueError) as error:
            raise ValueError(f"{self.manifest_path}: {error}") from error

    def _default_manifest(self) -> InstanceManifest:
        display_name = self.instance.name.replace("-", " ").replace("_", " ").title()
        return InstanceManifest(
            display_name=display_name,
            representation_label="Evidence-backed interview agent",
            disclosure=(
                f"This is an AI representation of {display_name}, "
                "not the person themself."
            ),
            welcome_message=(
                "Ask me about my work, background, or how I approach "
                "professional decisions."
            ),
            suggested_questions=(
                "Tell me about your professional background.",
                "What project best represents your work?",
                "What did you learn from a difficult engineering decision?",
            ),
        )

    def _write_manifest(self, manifest: InstanceManifest) -> None:
        payload = manifest.model_dump(mode="json", exclude_none=True)
        content = yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=False,
        )
        atomic_write(self.manifest_path, content.encode("utf-8"))

    def _materialize(
        self, drafts: tuple[RetrievalRecordDraft, ...]
    ) -> tuple[RetrievalRecord, ...]:
        records = tuple(
            RetrievalRecord(
                id=(draft.id or stable_id("record", draft.subject.strip().casefold())),
                subject=draft.subject.strip(),
                body=draft.body.strip(),
                url=(
                    AnyHttpUrl(normalize_url(str(draft.url)))
                    if draft.url is not None
                    else None
                ),
            )
            for draft in drafts
        )
        self._validate_records(records)
        return tuple(sorted(records, key=lambda record: record.id))

    def _validate_records(self, records: tuple[RetrievalRecord, ...]) -> None:
        ids = [record.id for record in records]
        if len(ids) != len(set(ids)):
            raise ValueError("retrieval record IDs must be unique")
        subjects = [record.subject.casefold() for record in records]
        if len(subjects) != len(set(subjects)):
            raise ValueError("retrieval record subjects must be unique")
        urls = [normalize_url(str(record.url)) for record in records if record.url]
        if len(urls) != len(set(urls)):
            raise ValueError("retrieval record URLs must be unique")

    def _write_index(self, records: tuple[RetrievalRecord, ...]) -> None:
        payload = [
            record.model_dump(mode="json", exclude_none=True) for record in records
        ]
        atomic_write(
            self.index_path,
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
                sort_keys=False,
            ).encode("utf-8")
            + b"\n",
        )

    def _index_result(
        self,
        records: tuple[RetrievalRecord, ...],
        *,
        changed_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        return {
            "index": str(self.index_path),
            "record_count": len(records),
            "changed_ids": list(changed_ids),
        }

    def _normalize_pdf(self, resume: Path) -> str:
        reader = PdfReader(resume)
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        normalized = "\n\n".join(page for page in pages if page).strip()
        if not normalized:
            raise ValueError(f"{resume}: PDF contains no extractable text")
        return f"{normalized}\n"

    def _normalize_markdown(self, content: bytes) -> str:
        text = content.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        normalized = text.strip()
        if not normalized:
            raise ValueError("resume Markdown is empty")
        return f"{normalized}\n"


def normalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
        raise ValueError("record URL must be HTTP(S)")
    scheme = parts.scheme.casefold()
    hostname = parts.hostname.casefold()
    port = parts.port
    netloc = hostname
    if port and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if key.casefold() not in TRACKING_QUERY_KEYS
            and not key.casefold().startswith(TRACKING_QUERY_PREFIXES)
        )
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, query, ""))
