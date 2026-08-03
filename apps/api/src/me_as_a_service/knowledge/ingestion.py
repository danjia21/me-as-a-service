import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from me_as_a_service.knowledge.models import (
    FurtherReading,
    KnowledgeScope,
    Passage,
    SourceDocument,
)

_HEADING_PATTERN = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_LIST_ITEM_PATTERN = re.compile(r"^(?:[-+*]|\d+\.)[ \t]+(.+)$")
_FURTHER_READING_PATTERN = re.compile(r"^(.+?):\s*(https?://\S+)$")
_FURTHER_READING_HEADING = "further reading"


class IngestionError(ValueError):
    """Raised when a curated source violates the ingestion contract."""


class _SourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)


@dataclass(frozen=True)
class _Heading:
    level: int
    title: str
    line_index: int


@dataclass(frozen=True)
class _EvidenceRecord:
    section_path: tuple[str, ...]
    text: str
    query_hints: tuple[str, ...] = ()


def load_markdown_source(
    path: Path, *, scope: KnowledgeScope | None = None
) -> SourceDocument:
    """Load a curated Markdown source into stable, section-aware passages."""
    raw_text = path.read_text(encoding="utf-8")
    metadata_lines, body_lines = _split_front_matter(raw_text)
    metadata = _parse_metadata(metadata_lines)
    passages = _build_passages(path, metadata, body_lines)

    if not passages:
        raise IngestionError("source body must contain at least one passage")

    return SourceDocument(
        source_id=metadata.id,
        title=metadata.title,
        scope=scope or _infer_source_scope(path),
        checksum=sha256(raw_text.encode("utf-8")).hexdigest(),
        passages=passages,
    )


def load_markdown_corpus(root: Path) -> tuple[SourceDocument, ...]:
    """Load every Markdown source below a corpus root in path order."""
    documents: list[SourceDocument] = []
    source_ids: set[str] = set()
    for path in sorted(root.rglob("*.md")):
        document = load_markdown_source(path, scope=_source_scope(root, path))
        if document.source_id in source_ids:
            raise IngestionError(f"duplicate source id: {document.source_id}")
        source_ids.add(document.source_id)
        documents.append(document)
    return tuple(documents)


def _source_scope(root: Path, path: Path) -> KnowledgeScope:
    relative_parts = path.relative_to(root).parts
    if len(relative_parts) == 1:
        return "resume"
    if relative_parts[0] == "personal":
        return "personal"
    if relative_parts[0] == "public":
        return "public"
    raise IngestionError(
        "Markdown knowledge sources must be at the knowledge root or below "
        f"personal/ or public/: {path}"
    )


def _infer_source_scope(path: Path) -> KnowledgeScope:
    for parent in path.parents:
        if parent.name == "personal":
            return "personal"
        if parent.name == "public":
            return "public"
    return "resume"


def _split_front_matter(raw_text: str) -> tuple[list[str], list[str]]:
    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise IngestionError("source must start with YAML-style front matter")

    try:
        closing_index = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as error:
        raise IngestionError("source front matter is not closed") from error

    return lines[1:closing_index], lines[closing_index + 1 :]


def _parse_metadata(lines: list[str]) -> _SourceMetadata:
    values: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=2):
        if not line.strip():
            continue

        key, separator, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not separator or not key or not value:
            raise IngestionError(f"invalid front-matter field on line {line_number}")
        if key in values:
            raise IngestionError(f"duplicate front-matter field: {key}")
        values[key] = value

    try:
        return _SourceMetadata.model_validate(values)
    except ValidationError as error:
        raise IngestionError(f"invalid source metadata: {error}") from error


def _build_passages(
    path: Path, metadata: _SourceMetadata, lines: list[str]
) -> tuple[Passage, ...]:
    lines, further_reading = _extract_further_reading(lines)
    headings = _find_headings(lines)
    if path.parent.name == "personal" or any(
        heading.level == 1 and heading.title.casefold() == "approved account"
        for heading in headings
    ):
        records = _build_personal_account_records(lines, headings)
    elif any(
        heading.level == 2 and heading.title.casefold() == "experience"
        for heading in headings
    ):
        records = _build_profile_records(lines, headings)
    else:
        records = _build_generic_records(lines, headings)

    passages: list[Passage] = []
    passage_ids: set[str] = set()

    for record in records:
        canonical_content = "\n".join((metadata.id, *record.section_path, record.text))
        content_digest = sha256(canonical_content.encode("utf-8")).hexdigest()
        passage_id = f"{metadata.id}:{content_digest[:20]}"
        if passage_id in passage_ids:
            raise IngestionError(
                "duplicate passage content within the same section would create "
                f"an ambiguous identifier: {passage_id}"
            )

        passage_ids.add(passage_id)
        passages.append(
            Passage(
                passage_id=passage_id,
                source_id=metadata.id,
                source_title=metadata.title,
                section_path=record.section_path,
                query_hints=record.query_hints,
                text=record.text,
                ordinal=len(passages),
                further_reading=further_reading,
            )
        )
    return tuple(passages)


def _extract_further_reading(
    lines: list[str],
) -> tuple[list[str], tuple[FurtherReading, ...]]:
    headings = _find_headings(lines)
    heading = next(
        (
            candidate
            for candidate in headings
            if candidate.title.casefold() == _FURTHER_READING_HEADING
        ),
        None,
    )
    if heading is None:
        return lines, ()

    end = _section_end(headings, heading, len(lines))
    entries = _parse_further_reading(lines[heading.line_index + 1 : end])
    remaining_lines = lines[: heading.line_index] + lines[end:]
    return remaining_lines, entries


def _parse_further_reading(lines: list[str]) -> tuple[FurtherReading, ...]:
    entries: list[FurtherReading] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        list_match = _LIST_ITEM_PATTERN.match(stripped)
        item_text = list_match.group(1) if list_match else stripped
        match = _FURTHER_READING_PATTERN.match(item_text)
        if not match:
            raise IngestionError(
                "further reading entries must be formatted as "
                f"'Label: https://url', got: {item_text!r}"
            )
        entries.append(
            FurtherReading(label=match.group(1).strip(), url=match.group(2).strip())
        )

    if not entries:
        raise IngestionError("further reading section must not be empty")
    return tuple(entries)


def _find_headings(lines: list[str]) -> tuple[_Heading, ...]:
    headings: list[_Heading] = []
    for line_index, line in enumerate(lines):
        match = _HEADING_PATTERN.match(line.strip())
        if match:
            headings.append(
                _Heading(
                    level=len(match.group(1)),
                    title=match.group(2).strip(),
                    line_index=line_index,
                )
            )
    return tuple(headings)


def _build_personal_account_records(
    lines: list[str], headings: tuple[_Heading, ...]
) -> tuple[_EvidenceRecord, ...]:
    top_level = {
        heading.title.casefold(): heading for heading in headings if heading.level == 1
    }
    approved_heading = top_level.get("approved account")
    if approved_heading is None:
        raise IngestionError(
            "personal account must contain an Approved account section"
        )

    approved_account = _section_text(lines, headings, approved_heading)
    if not approved_account:
        raise IngestionError(
            "personal account Approved account section must not be empty"
        )

    question_heading = top_level.get("interview question")
    question = (
        _section_text(lines, headings, question_heading) if question_heading else ""
    )
    boundaries_heading = top_level.get("evidence boundaries")
    boundaries = (
        _section_text(lines, headings, boundaries_heading) if boundaries_heading else ""
    )
    text = approved_account
    if boundaries:
        text = f"{text} Evidence boundaries: {boundaries}"

    return (
        _EvidenceRecord(
            section_path=("Approved account",),
            text=text,
            query_hints=(question,) if question else (),
        ),
    )


def _build_profile_records(
    lines: list[str], headings: tuple[_Heading, ...]
) -> tuple[_EvidenceRecord, ...]:
    records: list[_EvidenceRecord] = []
    first_level_two = next(
        (heading.line_index for heading in headings if heading.level == 2), len(lines)
    )
    first_level_one = next(
        (heading for heading in headings if heading.level == 1), None
    )
    introduction_start = (
        first_level_one.line_index + 1 if first_level_one is not None else 0
    )
    introduction = _normalize_content(lines[introduction_start:first_level_two])
    if introduction:
        records.append(_EvidenceRecord(section_path=(), text=introduction))

    level_two_headings = tuple(heading for heading in headings if heading.level == 2)
    for heading in level_two_headings:
        end = _section_end(headings, heading, len(lines))
        children = tuple(
            child
            for child in headings
            if child.level == 3 and heading.line_index < child.line_index < end
        )
        section_name = heading.title
        section_key = section_name.casefold()

        if section_key == "selected publications":
            records.extend(_publication_records(lines, heading, end))
            continue

        if children:
            direct_text = _normalize_content(
                lines[heading.line_index + 1 : children[0].line_index]
            )
            if direct_text:
                records.append(
                    _EvidenceRecord(section_path=(section_name,), text=direct_text)
                )
            for child in children:
                child_end = _section_end(headings, child, end)
                text = _normalize_content(
                    lines[child.line_index + 1 : child_end], include_headings=True
                )
                if text:
                    records.append(
                        _EvidenceRecord(
                            section_path=(section_name, child.title), text=text
                        )
                    )
            continue

        text = _normalize_content(lines[heading.line_index + 1 : end])
        if text:
            records.append(_EvidenceRecord(section_path=(section_name,), text=text))

    return tuple(records)


def _publication_records(
    lines: list[str], heading: _Heading, end: int
) -> tuple[_EvidenceRecord, ...]:
    records: list[_EvidenceRecord] = []
    current: list[str] = []
    for line in lines[heading.line_index + 1 : end]:
        match = _LIST_ITEM_PATTERN.match(line.strip())
        if match:
            text = _normalize_content(current)
            if text:
                records.append(
                    _EvidenceRecord(section_path=(heading.title,), text=text)
                )
            current = [match.group(1)]
        elif current and line.strip():
            current.append(line.strip())
    text = _normalize_content(current)
    if text:
        records.append(_EvidenceRecord(section_path=(heading.title,), text=text))
    return tuple(records)


def _build_generic_records(
    lines: list[str], headings: tuple[_Heading, ...]
) -> tuple[_EvidenceRecord, ...]:
    if not headings:
        text = _normalize_content(lines)
        return (_EvidenceRecord(section_path=(), text=text),) if text else ()

    top_level = min(heading.level for heading in headings)
    top_headings = tuple(heading for heading in headings if heading.level == top_level)
    records: list[_EvidenceRecord] = []
    preamble = _normalize_content(lines[: top_headings[0].line_index])
    if preamble:
        records.append(_EvidenceRecord(section_path=(), text=preamble))
    for heading in top_headings:
        end = _section_end(headings, heading, len(lines))
        text = _normalize_content(
            lines[heading.line_index + 1 : end], include_headings=True
        )
        if text:
            records.append(_EvidenceRecord(section_path=(heading.title,), text=text))
    return tuple(records)


def _section_end(
    headings: tuple[_Heading, ...], heading: _Heading, fallback: int
) -> int:
    return next(
        (
            candidate.line_index
            for candidate in headings
            if candidate.line_index > heading.line_index
            and candidate.level <= heading.level
        ),
        fallback,
    )


def _section_text(
    lines: list[str], headings: tuple[_Heading, ...], heading: _Heading
) -> str:
    end = _section_end(headings, heading, len(lines))
    return _normalize_content(lines[heading.line_index + 1 : end])


def _normalize_content(lines: list[str], *, include_headings: bool = False) -> str:
    content: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        heading_match = _HEADING_PATTERN.match(stripped)
        if heading_match:
            if include_headings:
                content.append(f"{heading_match.group(2).strip()}:")
            continue
        list_match = _LIST_ITEM_PATTERN.match(stripped)
        content.append(list_match.group(1) if list_match else stripped)
    return " ".join(" ".join(content).split())
