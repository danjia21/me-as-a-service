from pathlib import Path

import pytest

from me_as_a_service.chat.prompts import DEFAULT_PROMPT_DIRECTORY, load_prompts
from me_as_a_service.knowledge.models import FurtherReading, Passage


def _write_prompt_set(directory: Path, *, grounded: str = "Grounded") -> None:
    contents = {
        "system.md": "You are {display_name}.",
        "grounded.md": grounded,
        "web-grounded.md": "Web grounded",
        "insufficient-evidence.md": "Insufficient",
        "privacy-boundary.md": "Private",
        "redirected.md": "Redirected",
        "turn-analysis.md": "Analyze {display_name}: {personal_terms}",
        "evidence-sufficiency.md": "Judge",
    }
    for filename, content in contents.items():
        (directory / filename).write_text(f"{content}\n", encoding="utf-8")


def test_prompt_revision_is_stable_and_content_sensitive(tmp_path: Path) -> None:
    _write_prompt_set(tmp_path)
    first = load_prompts(tmp_path)
    load_prompts.cache_clear()
    second = load_prompts(tmp_path)

    assert first.revision == second.revision
    assert first.system_policy("Rowan") == "You are Rowan."
    assert first.turn_analysis_policy("Rowan", ("lantern",)) == (
        "Analyze Rowan: lantern"
    )

    _write_prompt_set(tmp_path, grounded="Changed")
    load_prompts.cache_clear()
    changed = load_prompts(tmp_path)
    assert changed.revision != first.revision


def test_generation_turn_message_combines_evidence_and_question(
    tmp_path: Path,
) -> None:
    _write_prompt_set(tmp_path)
    prompts = load_prompts(tmp_path)
    passage = Passage(
        passage_id="topic:abc",
        source_id="topic",
        section_path=("Section",),
        text="Grounded public evidence.",
        ordinal=0,
        further_reading=(
            FurtherReading(label="Example paper", url="https://example.org/paper"),
        ),
    )

    instruction = prompts.generation_turn_message(
        "grounded", (passage,), "What did you build?"
    )

    assert "Grounded public evidence." in instruction
    assert "Supporting facts:" in instruction
    assert "(Section) Grounded public evidence." in instruction
    assert "Further reading: Example paper: https://example.org/paper" in instruction
    assert instruction.endswith("User question:\nWhat did you build?")


def test_generation_turn_message_omits_further_reading_line_when_absent(
    tmp_path: Path,
) -> None:
    _write_prompt_set(tmp_path)
    prompts = load_prompts(tmp_path)
    passage = Passage(
        passage_id="topic:abc",
        source_id="topic",
        section_path=("Section",),
        text="Grounded public evidence.",
        ordinal=0,
    )

    instruction = prompts.generation_turn_message("grounded", (passage,), "Question?")

    assert "Further reading" not in instruction


def test_generation_turn_message_omits_generic_approved_account_section(
    tmp_path: Path,
) -> None:
    _write_prompt_set(tmp_path)
    prompts = load_prompts(tmp_path)
    passage = Passage(
        passage_id="topic:abc",
        source_id="topic",
        section_path=("Approved account",),
        text="First-person account.",
        ordinal=0,
    )

    instruction = prompts.generation_turn_message("grounded", (passage,), "Question?")

    assert "(Approved account)" not in instruction


def test_missing_prompt_file_fails_clearly(tmp_path: Path) -> None:
    _write_prompt_set(tmp_path)
    (tmp_path / "redirected.md").unlink()
    load_prompts.cache_clear()

    with pytest.raises(RuntimeError, match="Required prompt file is unreadable"):
        load_prompts(tmp_path)


def test_insufficient_evidence_prompt_defers_without_answering() -> None:
    prompts = load_prompts(DEFAULT_PROMPT_DIRECTORY)
    prompt = " ".join(prompts.insufficient_evidence.split())

    assert "Do not supply or infer a substantive answer" in prompt
    assert "Engage with the specific question" in prompt
    assert "generic praise" in prompt
    assert "invite the user to discuss it with you directly" in prompt
    assert "do not force it into every reply" in prompt
    assert "Vary the wording and rhythm across turns" in prompt
    assert "practical reason" not in prompt


def test_public_professional_contact_is_retrieved_and_answered_directly() -> None:
    prompts = load_prompts(DEFAULT_PROMPT_DIRECTORY)
    turn_analysis = " ".join(prompts.turn_analysis.split())
    grounded = " ".join(prompts.grounded.split())

    assert "published professional contact channel is not private" in turn_analysis
    assert "published professional contact channels" in turn_analysis
    assert "give the published professional contact channel directly" in grounded
    assert "Do not offer private contact details" in grounded


def test_public_context_route_has_a_narrow_web_search_boundary() -> None:
    prompts = load_prompts(DEFAULT_PROMPT_DIRECTORY)
    turn_analysis = " ".join(prompts.turn_analysis.split())
    web_grounded = " ".join(prompts.web_grounded.split())

    assert "`public_context`" in turn_analysis
    assert "directly connected" in turn_analysis
    assert "new claim" in turn_analysis
    assert "Search exactly once" in web_grounded
    assert "authoritative primary sources" in web_grounded
    assert "represented person's actions" in web_grounded
