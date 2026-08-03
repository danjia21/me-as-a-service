import pytest

from me_as_a_service.knowledge import ScopedEvidenceRetriever
from me_as_a_service.knowledge.models import KnowledgeScope, Passage, SourceDocument


def _document(scope: KnowledgeScope, name: str, passage_count: int) -> SourceDocument:
    return SourceDocument(
        source_id=name,
        title=name,
        scope=scope,
        checksum="0" * 64,
        passages=tuple(
            Passage(
                passage_id=f"{name}:{index}",
                source_id=name,
                source_title=name,
                section_path=("Evidence",),
                text=f"Shared searchable evidence {index}.",
                ordinal=index,
            )
            for index in range(passage_count)
        ),
    )


def test_scoped_retrieval_applies_fixed_ceilings_in_group_order() -> None:
    retriever = ScopedEvidenceRetriever(
        (
            _document("resume", "resume", 2),
            _document("personal", "personal", 4),
            _document("public", "public", 4),
        )
    )

    results = retriever.search("shared searchable evidence")

    assert [result.scope for result in results] == [
        "resume",
        "personal",
        "personal",
        "personal",
        "public",
        "public",
        "public",
    ]
    assert [result.rank_within_scope for result in results] == [1, 1, 2, 3, 1, 2, 3]
    assert len(results) == 7


def test_scoped_retrieval_allows_empty_and_underfilled_scopes() -> None:
    retriever = ScopedEvidenceRetriever(
        (
            _document("resume", "resume", 1),
            _document("public", "public", 1),
        )
    )

    results = retriever.search("shared")

    assert [(result.scope, result.rank_within_scope) for result in results] == [
        ("resume", 1),
        ("public", 1),
    ]


def test_scoped_retrieval_rejects_duplicate_candidate_ids_across_scopes() -> None:
    resume = _document("resume", "duplicate", 1)
    personal = _document("personal", "duplicate", 1)

    with pytest.raises(ValueError, match="duplicate passage ID: duplicate:0"):
        ScopedEvidenceRetriever((resume, personal))
