from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, TypeAdapter

from me_as_a_service.chat.types import TurnRoute


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    question: str
    question_type: str
    answerability: Literal["answerable", "insufficient_evidence"]
    expected_route: TurnRoute
    must_cite: bool
    prior_user_messages: tuple[str, ...]
    expected_sources: tuple[str, ...]
    required_facts: tuple[str, ...]
    relevant_sections: tuple[str, ...]


def load_evaluation_cases(path: Path) -> tuple[EvaluationCase, ...]:
    raw_cases = yaml.safe_load(path.read_text(encoding="utf-8"))
    return TypeAdapter(tuple[EvaluationCase, ...]).validate_python(raw_cases)
