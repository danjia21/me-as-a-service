from importlib.metadata import version
from pathlib import Path

import pytest
import tantivy

from me_as_a_service.evaluation import EvaluationCase, load_evaluation_cases
from me_as_a_service.instance import load_instance
from me_as_a_service.knowledge import LexicalRetriever, load_markdown_corpus
from me_as_a_service.knowledge.models import Passage

REPOSITORY_ROOT = Path(__file__).parents[3]
INSTANCE = load_instance(REPOSITORY_ROOT / "examples/fictional-profile")
QUESTIONS_PATH = INSTANCE.evaluation_questions
if QUESTIONS_PATH is None:
    raise RuntimeError("fictional instance must include evaluation questions")


EVALUATION_CASES = (
    load_evaluation_cases(QUESTIONS_PATH) if QUESTIONS_PATH.exists() else ()
)
ANSWERABLE_CASES = tuple(
    case
    for case in EVALUATION_CASES
    if case.expected_route == "grounded"
    and case.question_type not in {"contextual_follow_up", "contextual_correction"}
)
CONTEXTUAL_ANSWERABLE_CASES = tuple(
    case
    for case in EVALUATION_CASES
    if case.expected_route == "grounded"
    and case.question_type in {"contextual_follow_up", "contextual_correction"}
)


@pytest.fixture(scope="module")
def retriever() -> LexicalRetriever:
    sources = load_markdown_corpus(INSTANCE.knowledge_directory)
    return LexicalRetriever(
        passage for source in sources for passage in source.passages
    )


@pytest.mark.parametrize("case", ANSWERABLE_CASES, ids=lambda case: case.id)
def test_seed_question_retrieves_every_relevant_section(
    case: EvaluationCase,
    retriever: LexicalRetriever,
) -> None:
    results = retriever.search(case.question, top_k=12)
    retrieved_sections = {
        " > ".join(
            part.split(" | ", maxsplit=1)[0] for part in result.passage.section_path
        )
        for result in results
    }

    assert set(case.expected_sources) == {"profile"}
    assert set(case.relevant_sections) <= retrieved_sections


@pytest.mark.parametrize("case", CONTEXTUAL_ANSWERABLE_CASES, ids=lambda case: case.id)
def test_contextual_question_with_history_retrieves_every_relevant_section(
    case: EvaluationCase,
    retriever: LexicalRetriever,
) -> None:
    query = " ".join((*case.prior_user_messages, case.question))
    results = retriever.search(query, top_k=12)
    retrieved_sections = {
        " > ".join(
            part.split(" | ", maxsplit=1)[0] for part in result.passage.section_path
        )
        for result in results
    }

    assert set(case.expected_sources) == {"profile"}
    assert set(case.relevant_sections) <= retrieved_sections


def test_lantern_factual_passage_is_in_the_top_results(
    retriever: LexicalRetriever,
) -> None:
    results = retriever.search("What is Lantern, and what did Rowan build?")

    assert any("event-replay system" in result.passage.text for result in results[:4])


def test_query_without_shared_terms_has_no_results(
    retriever: LexicalRetriever,
) -> None:
    assert retriever.search("zygomatic xylophone") == ()


def test_pinned_tantivy_binding_is_importable() -> None:
    assert tantivy.Index is not None
    assert version("tantivy") == "0.26.0"


def test_retriever_uses_an_in_memory_tantivy_index_and_original_passages() -> None:
    passage = Passage(
        passage_id="source:first",
        source_id="source",
        source_title="Source title",
        section_path=("Experience",),
        text="Designed a retrieval service.",
        ordinal=0,
    )

    local_retriever = LexicalRetriever((passage,))
    results = local_retriever.search("retrieval")

    assert isinstance(local_retriever._index, tantivy.Index)
    assert local_retriever._index.searcher().num_docs == 1
    assert results[0].passage is passage


def test_equal_scores_use_corpus_order_as_secondary_sort() -> None:
    passages = tuple(
        Passage(
            passage_id=f"source:{name}",
            source_id="source",
            section_path=(),
            text="Identical searchable evidence.",
            ordinal=0,
        )
        for name in ("second", "first")
    )

    results = LexicalRetriever(passages).search("searchable")

    assert [result.passage.passage_id for result in results] == [
        "source:second",
        "source:first",
    ]


@pytest.mark.parametrize(
    "query",
    (
        "AND",
        "text:Lantern",
        "(Lantern OR Harbor)",
        'Lantern " OR *',
    ),
)
def test_visitor_query_syntax_is_treated_as_search_text(
    query: str, retriever: LexicalRetriever
) -> None:
    retriever.search(query)


def test_query_hint_locates_account_but_is_not_returned_as_evidence() -> None:
    passage = Passage(
        passage_id="account:first",
        source_id="account",
        source_title="Account title",
        section_path=("Approved account",),
        query_hints=("Why was the project started?",),
        text="The approved evidence describes the implementation.",
        ordinal=0,
    )

    result = LexicalRetriever((passage,)).search("Why was the project started?")[0]

    assert result.passage is passage
    assert "Why was the project started?" not in result.passage.text


@pytest.mark.parametrize("query", ("DR-SPAAM", "Person-MinkUNet", "Northstar’s"))
def test_punctuation_bearing_and_unicode_names_remain_searchable(query: str) -> None:
    passage = Passage(
        passage_id="names:first",
        source_id="names",
        section_path=(),
        text="DR-SPAAM and Person-MinkUNet were developed before Northstar’s platform.",
        ordinal=0,
    )

    assert LexicalRetriever((passage,)).search(query)[0].passage is passage


def test_top_k_must_be_positive() -> None:
    with pytest.raises(ValueError, match="top_k must be positive"):
        LexicalRetriever(()).search("anything", top_k=0)


@pytest.mark.skipif(
    not QUESTIONS_PATH.exists(), reason="optional evaluation fixture is absent"
)
def test_insufficient_evidence_case_has_no_gold_sections() -> None:
    insufficient_cases = [
        case
        for case in EVALUATION_CASES
        if case.answerability == "insufficient_evidence"
    ]

    assert len(EVALUATION_CASES) == 9
    assert len(insufficient_cases) == 4
    assert all(case.relevant_sections == () for case in insufficient_cases)
