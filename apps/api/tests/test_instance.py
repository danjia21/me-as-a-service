import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from me_as_a_service.instance import load_instance, load_selected_instance

REPOSITORY_ROOT = Path(__file__).parents[3]
FICTIONAL_INSTANCE = REPOSITORY_ROOT / "examples/fictional-profile"


def test_loads_the_selected_instance_from_one_environment_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAAS_INSTANCE_DIR", str(FICTIONAL_INSTANCE))

    instance = load_selected_instance()

    assert instance.config.display_name == "Rowan Vale"
    assert instance.knowledge_directory == FICTIONAL_INSTANCE / "knowledge"
    assert (
        instance.evaluation_questions
        == FICTIONAL_INSTANCE / "evaluations/questions.yaml"
    )


def test_temporary_instance_requires_no_source_changes(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "profile.md").write_text(
        "---\nid: temporary\ntitle: Temporary profile\n---\n\n# Work\n\nEvidence.\n",
        encoding="utf-8",
    )
    _write_manifest(tmp_path, display_name="Temporary Person")

    instance = load_instance(tmp_path)

    assert instance.config.display_name == "Temporary Person"
    assert instance.knowledge_directory == knowledge
    assert "You are Temporary Person." in instance.system_policy
    assert instance.config.disclosure not in instance.system_policy
    assert "the interface handles disclosure" in instance.system_policy


def test_api_starts_with_a_temporary_instance(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "profile.md").write_text(
        "---\nid: temporary\ntitle: Temporary profile\n---\n\n# Work\n\nEvidence.\n",
        encoding="utf-8",
    )
    _write_manifest(tmp_path, display_name="Temporary Person")
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(REPOSITORY_ROOT / "apps/api/src"),
        "OPENAI_API_KEY": "test-key",
        "LANGSMITH_TRACING": "false",
        "MAAS_CONVERSATION_STORE": "memory",
        "MAAS_INSTANCE_DIR": str(tmp_path),
    }

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from me_as_a_service.api import instance; "
                "print(instance.config.display_name)"
            ),
        ],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.stdout.strip() == "Temporary Person"


@pytest.mark.parametrize(
    "unsafe_path",
    ("../private", "knowledge/../../private", "/absolute/path"),
)
def test_manifest_paths_cannot_escape_the_instance(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    (tmp_path / "knowledge").mkdir()
    _write_manifest(tmp_path, knowledge_path=unsafe_path)

    with pytest.raises(ValidationError, match="remain inside the instance"):
        load_instance(tmp_path)


def test_manifest_rejects_unknown_fields(tmp_path: Path) -> None:
    (tmp_path / "knowledge").mkdir()
    manifest = _manifest()
    manifest["unexpected"] = True
    (tmp_path / "instance.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_instance(tmp_path)


def _write_manifest(
    root: Path,
    *,
    display_name: str = "Example Person",
    knowledge_path: str = "knowledge",
) -> None:
    manifest = _manifest()
    manifest["display_name"] = display_name
    manifest["knowledge"] = {"path": knowledge_path}
    (root / "instance.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )


def _manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "id": "temporary",
        "display_name": "Example Person",
        "representation_label": "Interview agent",
        "disclosure": "This is an AI representation.",
        "knowledge": {"path": "knowledge"},
        "suggested_questions": ["What did this person build?"],
        "links": {},
        "routing": {
            "personal_terms": ["person", "work"],
        },
    }
