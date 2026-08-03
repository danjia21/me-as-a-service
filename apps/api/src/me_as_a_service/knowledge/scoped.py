from collections.abc import Iterable
from pathlib import Path

from me_as_a_service.knowledge.ingestion import load_markdown_corpus
from me_as_a_service.knowledge.lexical import LexicalRetriever
from me_as_a_service.knowledge.models import KnowledgeScope, Passage, SourceDocument
from me_as_a_service.knowledge.retrieval import ScopedRetrievalResult

_SCOPE_LIMITS: tuple[tuple[KnowledgeScope, int], ...] = (
    ("resume", 1),
    ("personal", 3),
    ("public", 3),
)


class ScopedEvidenceRetriever:
    """Search resume, personal, and public evidence independently."""

    def __init__(self, documents: Iterable[SourceDocument]) -> None:
        passages_by_scope: dict[KnowledgeScope, list[Passage]] = {
            "resume": [],
            "personal": [],
            "public": [],
        }
        passage_ids: set[str] = set()
        for document in documents:
            for passage in document.passages:
                if passage.passage_id in passage_ids:
                    raise ValueError(f"duplicate passage ID: {passage.passage_id}")
                passage_ids.add(passage.passage_id)
                passages_by_scope[document.scope].append(passage)

        self._retrievers = {
            scope: LexicalRetriever(passages)
            for scope, passages in passages_by_scope.items()
        }

    @classmethod
    def from_directory(cls, knowledge_directory: Path) -> "ScopedEvidenceRetriever":
        return cls(load_markdown_corpus(knowledge_directory))

    def search(self, query: str) -> tuple[ScopedRetrievalResult, ...]:
        candidates: list[ScopedRetrievalResult] = []
        for scope, limit in _SCOPE_LIMITS:
            results = self._retrievers[scope].search(query, top_k=limit)
            candidates.extend(
                ScopedRetrievalResult(
                    passage=result.passage,
                    score=result.score,
                    scope=scope,
                    rank_within_scope=rank,
                )
                for rank, result in enumerate(results, start=1)
            )
        return tuple(candidates)
