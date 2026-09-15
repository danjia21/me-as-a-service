"""Load and search one instance's retrieval documents."""

from collections.abc import Mapping
from dataclasses import dataclass
from json import dumps
from typing import cast

import tantivy

from me_as_a_service.instance import Instance

_SEARCH_FIELDS = ("subject", "body")
_FIELD_BOOSTS = {"subject": 2.0, "body": 1.0}
_REQUIRED_FIELDS = frozenset(("id", "subject", "body"))
_ALLOWED_FIELDS = _REQUIRED_FIELDS | {"url"}


@dataclass(frozen=True, slots=True)
class Document:
    """One complete unit of knowledge available to retrieval consumers."""

    id: str
    subject: str
    body: str
    url: str | None = None


class KnowledgeLoadError(ValueError):
    """Raised when an instance's retrieval collection is invalid."""


class Knowledge:
    """An in-memory lexical retrieval index for one application instance."""

    def __init__(self, instance: Instance) -> None:
        self._documents = _load_documents(instance.records)
        self._documents_by_id = {document.id: document for document in self._documents}
        self._document_order = {
            document.id: order for order, document in enumerate(self._documents)
        }

        schema_builder = tantivy.SchemaBuilder()
        schema_builder.add_text_field("id", stored=True, tokenizer_name="raw")
        schema_builder.add_text_field("subject", tokenizer_name="en_stem")
        schema_builder.add_text_field("body", tokenizer_name="en_stem")
        self._index = tantivy.Index(schema_builder.build())

        writer = self._index.writer()
        for document in self._documents:
            writer.add_document(
                tantivy.Document(
                    id=document.id,
                    subject=document.subject,
                    body=document.body,
                )
            )
        writer.commit()
        self._index.reload()

    def retrieve(self, query: str, *, top_k: int = 5) -> tuple[Document, ...]:
        """Return the top ``top_k`` documents for ``query`` in relevance order."""

        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if not query.split() or not self._documents:
            return ()

        parsed_query = self._index.parse_query(
            " ".join(dumps(term, ensure_ascii=False) for term in query.split()),
            default_field_names=list(_SEARCH_FIELDS),
            field_boosts=_FIELD_BOOSTS,
        )
        searcher = self._index.searcher()
        hits = searcher.search(parsed_query, limit=len(self._documents)).hits
        ranked = [
            (
                float(score),
                self._documents_by_id[str(searcher.doc(address)["id"][0])],
            )
            for score, address in hits
        ]
        ranked.sort(
            key=lambda result: (
                -result[0],
                self._document_order[result[1].id],
            )
        )
        return tuple(document for _, document in ranked[:top_k])


def _load_documents(raw: tuple[object, ...]) -> tuple[Document, ...]:
    documents = tuple(
        _parse_document(value, index=index) for index, value in enumerate(raw)
    )
    ids = [document.id for document in documents]
    if len(ids) != len(set(ids)):
        raise KnowledgeLoadError("document IDs must be unique")
    return documents


def _parse_document(value: object, *, index: int) -> Document:
    location = f"knowledge index record {index}"
    if not isinstance(value, Mapping):
        raise KnowledgeLoadError(f"{location} must be an object")
    if not all(isinstance(field, str) for field in value):
        raise KnowledgeLoadError(f"{location} field names must be strings")
    record = cast(Mapping[str, object], value)

    fields = set(record)
    missing = _REQUIRED_FIELDS - fields
    if missing:
        raise KnowledgeLoadError(f"{location} is missing fields: {sorted(missing)}")
    unexpected = fields - _ALLOWED_FIELDS
    if unexpected:
        raise KnowledgeLoadError(
            f"{location} has unexpected fields: {sorted(unexpected)}"
        )

    document_id = _required_text(record["id"], field="id", location=location)
    subject = _required_text(record["subject"], field="subject", location=location)
    body = _required_text(record["body"], field="body", location=location)
    raw_url = record.get("url")
    if raw_url is not None and not isinstance(raw_url, str):
        raise KnowledgeLoadError(f"{location}.url must be a string or null")
    if isinstance(raw_url, str) and not raw_url.strip():
        raise KnowledgeLoadError(f"{location}.url must not be blank")

    return Document(id=document_id, subject=subject, body=body, url=raw_url)


def _required_text(value: object, *, field: str, location: str) -> str:
    if not isinstance(value, str):
        raise KnowledgeLoadError(f"{location}.{field} must be a string")
    if not value.strip():
        raise KnowledgeLoadError(f"{location}.{field} must not be blank")
    return value
