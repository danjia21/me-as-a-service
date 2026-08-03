from collections.abc import Iterable
from json import dumps

import tantivy

from me_as_a_service.knowledge.models import Passage
from me_as_a_service.knowledge.retrieval import RetrievalResult

_SEARCH_FIELDS = ["source_title", "section_path", "query_hints", "text"]
_FIELD_BOOSTS = {
    "source_title": 1.0,
    "section_path": 2.0,
    "query_hints": 2.0,
    "text": 1.0,
}


class LexicalRetriever:
    """An in-memory Tantivy lexical index over citable knowledge passages."""

    def __init__(self, passages: Iterable[Passage]) -> None:
        self._passages = tuple(passages)
        self._passages_by_id = {
            passage.passage_id: passage for passage in self._passages
        }
        if len(self._passages_by_id) != len(self._passages):
            raise ValueError("passage IDs must be unique")
        self._corpus_order = {
            passage.passage_id: order for order, passage in enumerate(self._passages)
        }

        schema_builder = tantivy.SchemaBuilder()
        schema_builder.add_text_field("passage_id", stored=True, tokenizer_name="raw")
        schema_builder.add_text_field("source_id", stored=True, tokenizer_name="raw")
        for field_name in _SEARCH_FIELDS:
            schema_builder.add_text_field(field_name, tokenizer_name="en_stem")
        self._index = tantivy.Index(schema_builder.build())

        writer = self._index.writer()
        for passage in self._passages:
            writer.add_document(
                tantivy.Document(
                    passage_id=passage.passage_id,
                    source_id=passage.source_id,
                    source_title=passage.source_title,
                    section_path=" ".join(passage.section_path),
                    query_hints=" ".join(passage.query_hints),
                    text=passage.text,
                )
            )
        writer.commit()
        self._index.reload()

    def search(self, query: str, *, top_k: int = 5) -> tuple[RetrievalResult, ...]:
        """Return the highest-scoring passages that share terms with the query."""
        if top_k <= 0:
            raise ValueError("top_k must be positive")

        if not query.split() or not self._passages:
            return ()

        parsed_query = self._index.parse_query(
            " ".join(dumps(term, ensure_ascii=False) for term in query.split()),
            default_field_names=_SEARCH_FIELDS,
            field_boosts=_FIELD_BOOSTS,
        )
        searcher = self._index.searcher()
        hits = searcher.search(parsed_query, limit=len(self._passages)).hits
        ranked = [
            RetrievalResult(
                passage=self._passages_by_id[
                    str(searcher.doc(address)["passage_id"][0])
                ],
                score=float(score),
            )
            for score, address in hits
        ]
        ranked.sort(
            key=lambda result: (
                -result.score,
                self._corpus_order[result.passage.passage_id],
            )
        )
        return tuple(ranked[:top_k])
