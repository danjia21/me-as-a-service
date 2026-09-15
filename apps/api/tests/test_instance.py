import json
from pathlib import Path

import pytest

from me_as_a_service.instance import (
    Instance,
    load_instance,
    load_instance_from_environment,
)


def evaluation_questions() -> list[dict[str, str]]:
    return [
        {"id": f"question_{index}", "question": f"Question {index}?"}
        for index in range(10)
    ]


def test_instance_exposes_its_owned_paths(tmp_path: Path) -> None:
    directory = tmp_path / "profile"
    (directory / "index").mkdir(parents=True)
    (directory / "evaluations").mkdir()
    (directory / "instance.yaml").write_text(
        "display_name: Test Profile\n",
        encoding="utf-8",
    )
    (directory / "index" / "records.json").write_text(
        json.dumps([{"id": "one", "subject": "One", "body": "Body"}]),
        encoding="utf-8",
    )
    (directory / "evaluations" / "evidence_required.json").write_text(
        json.dumps(evaluation_questions()),
        encoding="utf-8",
    )

    instance = load_instance(tmp_path / "profile" / ".." / "profile")

    assert instance.directory == (tmp_path / "profile").resolve()
    assert instance.manifest_path == instance.directory / "instance.yaml"
    assert instance.index_path == instance.directory / "index" / "records.json"
    assert instance.evaluation_questions_path == (
        instance.directory / "evaluations" / "evidence_required.json"
    )
    assert instance.manifest == {"display_name": "Test Profile"}
    assert instance.public_profile is None
    assert instance.records == ({"id": "one", "subject": "One", "body": "Body"},)
    assert instance.evaluation_questions() == {
        f"question_{index}": f"Question {index}?" for index in range(10)
    }


def test_instance_exposes_configured_public_profile(tmp_path: Path) -> None:
    directory = tmp_path / "profile"
    (directory / "index").mkdir(parents=True)
    (directory / "instance.yaml").write_text(
        "display_name: Test Profile\n"
        "links:\n"
        "  public_profile: https://www.linkedin.com/in/test-profile/\n",
        encoding="utf-8",
    )
    (directory / "index" / "records.json").write_text("[]", encoding="utf-8")

    assert Instance(directory).public_profile == (
        "https://www.linkedin.com/in/test-profile/"
    )


@pytest.mark.parametrize(
    ("questions", "message"),
    [
        (
            [*evaluation_questions()[:-1], evaluation_questions()[0]],
            "evaluation question IDs must be unique",
        ),
        (
            [
                {**question, "unexpected": "value"} if index == 0 else question
                for index, question in enumerate(evaluation_questions())
            ],
            "must contain exactly",
        ),
    ],
)
def test_instance_rejects_invalid_evaluation_questions(
    tmp_path: Path,
    questions: list[dict[str, str]],
    message: str,
) -> None:
    directory = tmp_path / "profile"
    (directory / "index").mkdir(parents=True)
    (directory / "evaluations").mkdir()
    (directory / "instance.yaml").write_text(
        "display_name: Test Profile\n",
        encoding="utf-8",
    )
    (directory / "index" / "records.json").write_text("[]", encoding="utf-8")
    (directory / "evaluations" / "evidence_required.json").write_text(
        json.dumps(questions),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        Instance(directory).evaluation_questions()


def test_load_instance_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "profile"
    (directory / "index").mkdir(parents=True)
    (directory / "instance.yaml").write_text("name: Profile\n", encoding="utf-8")
    (directory / "index" / "records.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("MAAS_INSTANCE_DIR", str(directory))

    assert load_instance_from_environment().directory == directory


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("instance.yaml", "- not-an-object\n", "manifest must be an object"),
        ("index/records.json", "{}", "records must be a JSON array"),
    ],
)
def test_instance_rejects_invalid_loaded_data(
    tmp_path: Path, filename: str, content: str, message: str
) -> None:
    directory = tmp_path / "profile"
    (directory / "index").mkdir(parents=True)
    (directory / "instance.yaml").write_text("name: Profile\n", encoding="utf-8")
    (directory / "index" / "records.json").write_text("[]", encoding="utf-8")
    (directory / filename).write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        Instance(directory)
