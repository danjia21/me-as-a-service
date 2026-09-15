import json
from pathlib import Path

import pytest

from me_as_a_service.instance import Instance
from me_as_a_service.knowledge import Document, Knowledge, KnowledgeLoadError


def build_knowledge(tmp_path: Path, records: list[dict[str, object]]) -> Knowledge:
    directory = tmp_path / "profile"
    (directory / "index").mkdir(parents=True)
    (directory / "instance.yaml").write_text("name: Profile\n", encoding="utf-8")
    (directory / "index" / "records.json").write_text(
        json.dumps(records), encoding="utf-8"
    )
    instance = Instance(directory)
    return Knowledge(instance)


def test_retrieve_returns_top_k_documents_from_the_instance_index(
    tmp_path: Path,
) -> None:
    knowledge = build_knowledge(
        tmp_path,
        [
            {
                "id": "record-robotics",
                "subject": "Robotics research",
                "body": "Designed perception systems for mobile robots.",
                "url": "https://example.com/robotics",
            },
            {
                "id": "record-platform",
                "subject": "Machine-learning platform",
                "body": "Built a model-serving framework for many engineers.",
            },
            {
                "id": "record-weather",
                "subject": "Weather station",
                "body": "Measured rainfall and wind.",
            },
        ],
    )

    assert knowledge.retrieve("robot perception platform", top_k=2) == (
        Document(
            id="record-robotics",
            subject="Robotics research",
            body="Designed perception systems for mobile robots.",
            url="https://example.com/robotics",
        ),
        Document(
            id="record-platform",
            subject="Machine-learning platform",
            body="Built a model-serving framework for many engineers.",
        ),
    )


def test_retrieve_handles_empty_queries_and_indexes(tmp_path: Path) -> None:
    knowledge = build_knowledge(tmp_path, [])

    assert knowledge.retrieve("anything") == ()
    assert knowledge.retrieve("   ") == ()


def test_retrieve_rejects_non_positive_top_k(tmp_path: Path) -> None:
    knowledge = build_knowledge(
        tmp_path,
        [{"id": "record-one", "subject": "One", "body": "Body"}],
    )

    with pytest.raises(ValueError, match="top_k must be positive"):
        knowledge.retrieve("one", top_k=0)


@pytest.mark.parametrize(
    ("records", "message"),
    [
        ([{"id": "record-one", "subject": "One"}], "missing fields"),
        (
            [
                {
                    "id": "record-one",
                    "subject": "One",
                    "body": "Body",
                    "legacy": "value",
                }
            ],
            "unexpected fields",
        ),
        (
            [
                {"id": "record-one", "subject": "One", "body": "First"},
                {"id": "record-one", "subject": "Two", "body": "Second"},
            ],
            "document IDs must be unique",
        ),
    ],
)
def test_loading_rejects_invalid_index_records(
    tmp_path: Path, records: object, message: str
) -> None:
    directory = tmp_path / "profile"
    (directory / "index").mkdir(parents=True)
    (directory / "instance.yaml").write_text("name: Profile\n", encoding="utf-8")
    (directory / "index" / "records.json").write_text(
        json.dumps(records), encoding="utf-8"
    )
    instance = Instance(directory)

    with pytest.raises(KnowledgeLoadError, match=message):
        Knowledge(instance)
