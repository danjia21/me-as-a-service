from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from maas_knowledge.cli import main
from maas_knowledge.service import KnowledgeInitializer, normalize_url


def write_yaml(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def proposal(path: Path, records: list[dict[str, Any]]) -> Path:
    return write_yaml(path, {"schema_version": 1, "records": records})


@pytest.fixture
def initialized(tmp_path: Path) -> tuple[KnowledgeInitializer, Path]:
    instance = tmp_path / "profile"
    service = KnowledgeInitializer(instance)
    result = service.initialize()
    assert result["record_count"] == 0
    assert json.loads((instance / "index/records.json").read_text()) == []
    assert not (instance / "sources").exists()
    assert not (instance / "workspace").exists()
    assert not (instance / "published").exists()
    manifest = yaml.safe_load((instance / "instance.yaml").read_text())
    assert manifest == {
        "display_name": "Profile",
        "representation_label": "Evidence-backed interview agent",
        "disclosure": (
            "This is an AI representation of Profile, not the person themself."
        ),
        "welcome_message": (
            "Ask me about my work, background, or how I approach "
            "professional decisions."
        ),
        "knowledge_base": {"index": "index/records.json"},
        "suggested_questions": [
            "Tell me about your professional background.",
            "What project best represents your work?",
            "What did you learn from a difficult engineering decision?",
        ],
        "links": {},
    }
    return service, tmp_path


def test_init_migrates_an_older_minimal_manifest(tmp_path: Path) -> None:
    instance = tmp_path / "selected-profile"
    instance.mkdir()
    write_yaml(
        instance / "instance.yaml",
        {
            "schema_version": 3,
            "id": "casey-morgan",
            "knowledge_base": {"index": "index/records.json"},
        },
    )

    KnowledgeInitializer(instance).initialize()

    manifest = yaml.safe_load((instance / "instance.yaml").read_text())
    assert "schema_version" not in manifest
    assert "id" not in manifest
    assert manifest["display_name"] == "Selected Profile"
    assert manifest["representation_label"] == "Evidence-backed interview agent"
    assert "Selected Profile" in manifest["disclosure"]
    assert "Ask me about my work" in manifest["welcome_message"]
    assert len(manifest["suggested_questions"]) == 3
    assert manifest["links"] == {}


def test_init_preserves_a_complete_custom_manifest(tmp_path: Path) -> None:
    instance = tmp_path / "casey"
    instance.mkdir()
    manifest_path = instance / "instance.yaml"
    write_yaml(
        manifest_path,
        {
            "display_name": "Casey Morgan",
            "representation_label": "Portfolio guide",
            "disclosure": "A tailored AI representation of Casey.",
            "welcome_message": "Ask me about my work on Beacon.",
            "knowledge_base": {"index": "index/records.json"},
            "suggested_questions": ["Why did you build Beacon?"],
            "links": {"public_profile": "https://example.com/casey"},
        },
    )
    before = manifest_path.read_bytes()

    KnowledgeInitializer(instance).initialize()

    assert manifest_path.read_bytes() == before


def test_resume_import_preserves_the_current_working_index(
    initialized: tuple[KnowledgeInitializer, Path],
) -> None:
    service, tmp_path = initialized
    service.replace_index(
        proposal(
            tmp_path / "baseline.yaml",
            [{"subject": "Career overview", "body": "Existing usable knowledge."}],
        )
    )
    before = service.index_path.read_bytes()
    resume = tmp_path / "resume.md"
    resume.write_text("# Casey Morgan\n\nStaff engineer.\n", encoding="utf-8")
    metadata = service.import_resume(resume)
    assert service.import_resume(resume) == metadata
    assert service.index_path.read_bytes() == before
    assert (service.resume_dir / "original").read_bytes() == resume.read_bytes()
    assert "Staff engineer" in (service.resume_dir / "normalized.md").read_text()
    assert set(json.loads((service.resume_dir / "metadata.json").read_text())) == {
        "schema_version",
        "source_id",
        "original_filename",
        "media_type",
        "sha256",
        "normalized_sha256",
    }


def test_replace_index_writes_only_the_four_field_retrieval_contract(
    initialized: tuple[KnowledgeInitializer, Path],
) -> None:
    service, tmp_path = initialized
    result = service.replace_index(
        proposal(
            tmp_path / "records.yaml",
            [
                {
                    "subject": "Project Beacon",
                    "body": "I led Project Beacon and reduced latency by 40%.",
                },
                {
                    "id": "record-public01",
                    "subject": "Beacon repository",
                    "body": "The repository documents the public project.",
                    "url": "https://GitHub.com/example/beacon/?utm_source=test",
                },
            ],
        )
    )
    assert result["record_count"] == 2
    records = json.loads(service.index_path.read_text())
    assert set(records[0]) <= {"id", "subject", "body", "url"}
    assert all(set(record) >= {"id", "subject", "body"} for record in records)
    public = next(record for record in records if "url" in record)
    assert public["url"] == "https://github.com/example/beacon"
    assert {record.id for record in service.records()} == set(result["changed_ids"])


def test_upsert_immediately_augments_or_updates_the_live_index(
    initialized: tuple[KnowledgeInitializer, Path],
) -> None:
    service, tmp_path = initialized
    baseline = service.replace_index(
        proposal(
            tmp_path / "baseline.yaml",
            [{"subject": "Career overview", "body": "Initial summary."}],
        )
    )
    overview_id = baseline["changed_ids"][0]
    service.upsert_index(
        proposal(
            tmp_path / "interview.yaml",
            [
                {
                    "id": overview_id,
                    "subject": "Career overview",
                    "body": "Updated summary with the new detail.",
                },
                {
                    "subject": "Beacon ingestion ownership",
                    "body": "I co-designed the boundary with the team.",
                },
            ],
        )
    )
    records = service.records()
    assert len(records) == 2
    overview = next(record for record in records if record.id == overview_id)
    assert overview.body.startswith("Updated")
    assert any(record.subject == "Beacon ingestion ownership" for record in records)

    service.remove_records(
        (next(record.id for record in records if record.id != overview_id),)
    )
    assert [record.id for record in service.records()] == [overview_id]


def test_invalid_update_leaves_the_existing_index_untouched(
    initialized: tuple[KnowledgeInitializer, Path],
) -> None:
    service, tmp_path = initialized
    service.replace_index(
        proposal(
            tmp_path / "baseline.yaml",
            [{"subject": "Career overview", "body": "Initial summary."}],
        )
    )
    before = service.index_path.read_bytes()
    invalid = proposal(
        tmp_path / "invalid.yaml",
        [
            {"id": "record-duplicate1", "subject": "Duplicate", "body": "One."},
            {"id": "record-duplicate1", "subject": "Other", "body": "Two."},
        ],
    )
    with pytest.raises(ValueError, match="IDs must be unique"):
        service.upsert_index(invalid)
    assert service.index_path.read_bytes() == before


def test_pdf_import_and_url_normalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Page:
        def extract_text(self) -> str:
            return "PDF resume text"

    class Reader:
        def __init__(self, _: Path) -> None:
            self.pages = [Page()]

    monkeypatch.setattr("maas_knowledge.service.PdfReader", Reader)
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-test")
    service = KnowledgeInitializer(tmp_path / "new")
    metadata = service.import_resume(resume)
    assert metadata.media_type == "application/pdf"
    assert "PDF resume text" in (service.resume_dir / "normalized.md").read_text()
    assert (
        normalize_url("HTTPS://Example.COM:443/a/?utm_source=x&b=2#part")
        == "https://example.com/a?b=2"
    )


def test_cli_emits_small_machine_readable_results_and_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    instance = tmp_path / "profile"
    assert main(["init", "--instance", str(instance)]) == 0
    success = json.loads(capsys.readouterr().out)
    assert success["ok"] is True
    assert success["result"]["index_present"] is True

    update = proposal(
        tmp_path / "records.yaml",
        [{"subject": "Career overview", "body": "A usable profile."}],
    )
    assert main(["replace-index", "--instance", str(instance), str(update)]) == 0
    replaced = json.loads(capsys.readouterr().out)
    assert replaced["result"]["record_count"] == 1

    assert main(["validate", "--instance", str(tmp_path / "missing")]) == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure["ok"] is False
    assert "file does not exist" in failure["error"]
