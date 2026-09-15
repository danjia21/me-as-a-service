from collections.abc import Callable
from typing import Self

import pytest

from me_as_a_service.chat import tracing as chat_tracing
from me_as_a_service.chat.tracing import LangSmithTracing


def test_wrapped_provider_call_has_a_specific_child_run_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_name: str | None = None

    def fake_wrap_openai(client: object, **kwargs: object) -> object:
        nonlocal observed_name
        observed_name = str(kwargs["chat_name"])
        return client

    class WrappableModel:
        def wrap_client(self, wrapper: Callable[[object], object]) -> Self:
            wrapper(object())
            return self

    monkeypatch.setattr(chat_tracing, "wrap_openai", fake_wrap_openai)

    tracing = LangSmithTracing(True, None, "test", (), {})
    model = WrappableModel()
    wrapped_model = tracing.wrap_chat_model(model)  # type: ignore[arg-type]

    assert wrapped_model is model  # type: ignore[comparison-overlap]
    assert observed_name == "openai_chat_completion"
