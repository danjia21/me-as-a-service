"""Knowledge-source ingestion and retrieval primitives."""

from me_as_a_service.knowledge.ingestion import (
    IngestionError,
    load_markdown_corpus,
    load_markdown_source,
)
from me_as_a_service.knowledge.lexical import LexicalRetriever
from me_as_a_service.knowledge.models import KnowledgeScope, Passage, SourceDocument
from me_as_a_service.knowledge.retrieval import (
    EvidenceRetriever,
    RetrievalResult,
    ScopedRetrievalResult,
)
from me_as_a_service.knowledge.scoped import ScopedEvidenceRetriever

__all__ = [
    "IngestionError",
    "EvidenceRetriever",
    "KnowledgeScope",
    "LexicalRetriever",
    "Passage",
    "RetrievalResult",
    "ScopedEvidenceRetriever",
    "ScopedRetrievalResult",
    "SourceDocument",
    "load_markdown_corpus",
    "load_markdown_source",
]
