from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from me_as_a_service.knowledge.models import KnowledgeScope, Passage


class RetrievalResult(BaseModel):
    """One evidence passage ranked by a retriever."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passage: Passage
    score: float = Field(gt=0)


class ScopedRetrievalResult(BaseModel):
    """One candidate ranked within one independently searched scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passage: Passage
    score: float = Field(gt=0)
    scope: KnowledgeScope
    rank_within_scope: int = Field(ge=1)


class EvidenceRetriever(Protocol):
    """Return the fixed grouped candidate allocation for one query."""

    def search(self, query: str) -> tuple[ScopedRetrievalResult, ...]: ...
