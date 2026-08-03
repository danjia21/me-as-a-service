from pathlib import Path

import pytest

from me_as_a_service.knowledge.ingestion import (
    IngestionError,
    load_markdown_corpus,
    load_markdown_source,
)

REPOSITORY_ROOT = Path(__file__).parents[3]
PROFILE_PATH = REPOSITORY_ROOT / "examples/fictional-profile/knowledge/profile.md"
KNOWLEDGE_PATH = REPOSITORY_ROOT / "examples/fictional-profile/knowledge"


def test_loads_profile_with_section_provenance() -> None:
    document = load_markdown_source(PROFILE_PATH)

    assert document.source_id == "profile"
    assert document.title == "Rowan Vale — Fictional professional profile"

    passage = next(
        item for item in document.passages if "event-replay system" in item.text
    )
    assert passage.section_path == (
        "Experience",
        "Northstar Mobility | Staff Reliability Engineer",
    )


def test_passage_identifiers_are_unique_and_deterministic() -> None:
    first_load = load_markdown_source(PROFILE_PATH)
    second_load = load_markdown_source(PROFILE_PATH)

    first_ids = [passage.passage_id for passage in first_load.passages]
    second_ids = [passage.passage_id for passage in second_load.passages]

    assert first_ids == second_ids
    assert len(first_ids) == len(set(first_ids))
    assert [passage.ordinal for passage in first_load.passages] == list(
        range(len(first_load.passages))
    )
    assert first_load.checksum == second_load.checksum


def test_corpus_loads_every_source_in_deterministic_path_order(tmp_path: Path) -> None:
    personal = tmp_path / "personal"
    public = tmp_path / "public"
    personal.mkdir()
    public.mkdir()
    (tmp_path / "resume.md").write_text(_source("resume", "Résumé"), encoding="utf-8")
    (personal / "project.md").write_text(
        _personal_account("project", "Project note"), encoding="utf-8"
    )
    (public / "publication.md").write_text(
        _source("publication", "Publication"), encoding="utf-8"
    )

    documents = load_markdown_corpus(tmp_path)

    assert [document.source_id for document in documents] == [
        "project",
        "publication",
        "resume",
    ]
    assert [document.scope for document in documents] == [
        "personal",
        "public",
        "resume",
    ]


def test_example_corpus_loads_profile_and_approved_accounts() -> None:
    documents = load_markdown_corpus(KNOWLEDGE_PATH)

    source_ids = {document.source_id for document in documents}
    assert source_ids == {
        "profile",
        "lantern-incident-workflow",
        "harbor-evaluation",
    }
    assert {document.source_id: document.scope for document in documents} == {
        "profile": "resume",
        "lantern-incident-workflow": "personal",
        "harbor-evaluation": "personal",
    }
    assert "interrupted-account" not in source_ids


def test_profile_role_is_one_coherent_record_and_publications_stay_separate(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "resume.md"
    source_path.write_text(
        """---
id: resume
title: Example résumé
---

# Example Person

Summary paragraph.

## Experience

### Example University | Researcher

_Aachen | 2019 -- 2023_

- Built DR-SPAAM.
- Built Person-MinkUNet.
- Supervised students.

## Selected Publications

1. DR-SPAAM paper.
2. Person-MinkUNet paper.
""",
        encoding="utf-8",
    )

    document = load_markdown_source(source_path)

    role = next(
        passage
        for passage in document.passages
        if passage.section_path
        == (
            "Experience",
            "Example University | Researcher",
        )
    )
    assert "2019 -- 2023" in role.text
    assert "Built DR-SPAAM" in role.text
    assert "Built Person-MinkUNet" in role.text
    assert "Supervised students" in role.text
    publications = [
        passage
        for passage in document.passages
        if passage.section_path == ("Selected Publications",)
    ]
    assert [passage.text for passage in publications] == [
        "DR-SPAAM paper.",
        "Person-MinkUNet paper.",
    ]


def test_approved_account_keeps_boundaries_and_uses_question_only_as_hint(
    tmp_path: Path,
) -> None:
    personal = tmp_path / "personal"
    personal.mkdir()
    source_path = personal / "account.md"
    source_path.write_text(
        _personal_account("account", "Approved account"), encoding="utf-8"
    )

    document = load_markdown_source(source_path)

    assert len(document.passages) == 1
    passage = document.passages[0]
    assert passage.source_title == "Approved account"
    assert passage.query_hints == ("What prompted the work?",)
    assert "What prompted the work?" not in passage.text
    assert "Grounded approved evidence." in passage.text
    assert "Evidence boundaries: No quantitative result is claimed." in passage.text


def test_personal_directory_rejects_document_without_approved_account(
    tmp_path: Path,
) -> None:
    personal = tmp_path / "personal"
    personal.mkdir()
    source_path = personal / "draft.md"
    source_path.write_text(_source("draft", "Draft"), encoding="utf-8")

    with pytest.raises(IngestionError, match="must contain an Approved account"):
        load_markdown_source(source_path)


def test_rejects_empty_approved_account(tmp_path: Path) -> None:
    source_path = tmp_path / "account.md"
    source_path.write_text(
        """---
id: account
title: Empty account
---

# Interview question

What happened?

# Approved account

# Evidence boundaries

- Nothing was approved.
""",
        encoding="utf-8",
    )

    with pytest.raises(IngestionError, match="must not be empty"):
        load_markdown_source(source_path)


def test_corpus_does_not_load_markdown_outside_configured_root(
    tmp_path: Path,
) -> None:
    knowledge = tmp_path / "knowledge"
    workspace = tmp_path / "workspace" / "research"
    knowledge.mkdir()
    workspace.mkdir(parents=True)
    (knowledge / "approved.md").write_text(
        _source("approved", "Approved"), encoding="utf-8"
    )
    (workspace / "candidate.md").write_text(
        _source("candidate", "Candidate"), encoding="utf-8"
    )

    documents = load_markdown_corpus(knowledge)

    assert [document.source_id for document in documents] == ["approved"]


def test_corpus_rejects_duplicate_source_ids(tmp_path: Path) -> None:
    (tmp_path / "first.md").write_text(
        _source("duplicate", "First source"), encoding="utf-8"
    )
    (tmp_path / "second.md").write_text(
        _source("duplicate", "Second source"), encoding="utf-8"
    )

    with pytest.raises(IngestionError, match="duplicate source id: duplicate"):
        load_markdown_corpus(tmp_path)


def test_corpus_rejects_markdown_outside_the_named_scope_directories(
    tmp_path: Path,
) -> None:
    unsupported = tmp_path / "notes"
    unsupported.mkdir()
    (unsupported / "source.md").write_text(
        _source("source", "Unsupported source"), encoding="utf-8"
    )

    with pytest.raises(IngestionError, match="personal/ or public/"):
        load_markdown_corpus(tmp_path)


def test_rejects_source_without_front_matter(tmp_path: Path) -> None:
    source_path = tmp_path / "invalid.md"
    source_path.write_text("# Missing metadata\n", encoding="utf-8")

    with pytest.raises(IngestionError, match="must start"):
        load_markdown_source(source_path)


def test_further_reading_is_parsed_and_excluded_from_passage_text(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "topic.md"
    source_path.write_text(
        """---
id: topic
title: Example public topic
---

## Section

Grounded public evidence.

## Further reading

- Example paper: https://example.org/paper
- Example repository: https://example.org/repo
""",
        encoding="utf-8",
    )

    document = load_markdown_source(source_path)

    assert len(document.passages) == 1
    passage = document.passages[0]
    assert "Further reading" not in passage.text
    assert "https://example.org" not in passage.text
    assert [(link.label, link.url) for link in passage.further_reading] == [
        ("Example paper", "https://example.org/paper"),
        ("Example repository", "https://example.org/repo"),
    ]


def test_rejects_empty_further_reading_section(tmp_path: Path) -> None:
    source_path = tmp_path / "topic.md"
    source_path.write_text(
        """---
id: topic
title: Example public topic
---

## Section

Grounded public evidence.

## Further reading
""",
        encoding="utf-8",
    )

    with pytest.raises(IngestionError, match="further reading section must not"):
        load_markdown_source(source_path)


def test_rejects_malformed_further_reading_entry(tmp_path: Path) -> None:
    source_path = tmp_path / "topic.md"
    source_path.write_text(
        """---
id: topic
title: Example public topic
---

## Section

Grounded public evidence.

## Further reading

- Not a link
""",
        encoding="utf-8",
    )

    with pytest.raises(IngestionError, match="further reading entries must be"):
        load_markdown_source(source_path)


def test_rejects_unknown_front_matter_fields(tmp_path: Path) -> None:
    source_path = tmp_path / "invalid.md"
    source_path.write_text(
        """---
id: invalid
title: Invalid source
unexpected: value
---

# Content

Evidence.
""",
        encoding="utf-8",
    )

    with pytest.raises(IngestionError, match="invalid source metadata"):
        load_markdown_source(source_path)


def _source(source_id: str, title: str) -> str:
    return f"""---
id: {source_id}
title: {title}
---

# Evidence

Grounded public evidence.
"""


def _personal_account(source_id: str, title: str) -> str:
    return f"""---
id: {source_id}
title: {title}
---

# Interview question

What prompted the work?

# Approved account

Grounded approved evidence.

# Evidence boundaries

- No quantitative result is claimed.
"""
