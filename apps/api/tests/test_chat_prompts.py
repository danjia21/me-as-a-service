from me_as_a_service.chat.prompts import load_prompts


def test_system_prompts_use_newlines_only_between_paragraphs() -> None:
    prompts = load_prompts()
    values = {
        "display_name": "Ada Example",
        "public_profile": "https://www.linkedin.com/in/ada-example/",
    }

    for name in (
        "answer-conversation",
        "answer-discuss-in-person",
        "answer-inappropriate",
        "answer-irrelevant",
        "answer-evidence-required",
        "classify-and-rewrite-message",
    ):
        rendered = prompts.render(name, values)

        paragraphs = rendered.split("\n\n")

        assert all(len(paragraph.splitlines()) == 1 for paragraph in paragraphs)


def test_classifier_prompt_routes_public_professional_contact_to_evidence() -> None:
    prompt = load_prompts().render(
        "classify-and-rewrite-message",
        {"display_name": "Ada Example"},
    )

    assert "must be `evidence_required`" in prompt
    assert '"public professional profile"' in prompt
    assert '"published professional contact"' in prompt
    assert "LinkedIn" in prompt
    assert "private address, phone number, personal email address" in prompt
