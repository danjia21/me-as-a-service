from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

from me_as_a_service.chat.types import TurnRoute
from me_as_a_service.knowledge.models import Passage

DEFAULT_PROMPT_DIRECTORY = Path(__file__).parents[1] / "prompts"
_PROMPT_FILES = {
    "system": "system.md",
    "grounded": "grounded.md",
    "web_grounded": "web-grounded.md",
    "insufficient_evidence": "insufficient-evidence.md",
    "privacy_boundary": "privacy-boundary.md",
    "redirected": "redirected.md",
    "turn_analysis": "turn-analysis.md",
    "evidence_sufficiency": "evidence-sufficiency.md",
}


@dataclass(frozen=True)
class PromptSet:
    system: str
    grounded: str
    web_grounded: str
    insufficient_evidence: str
    privacy_boundary: str
    redirected: str
    turn_analysis: str
    evidence_sufficiency: str
    revision: str

    def system_policy(self, display_name: str) -> str:
        return self.system.format(display_name=display_name)

    def turn_analysis_policy(
        self, display_name: str, personal_terms: tuple[str, ...]
    ) -> str:
        return self.turn_analysis.format(
            display_name=display_name,
            personal_terms=", ".join(personal_terms),
        )

    def generation_turn_message(
        self, route: TurnRoute, evidence: tuple[Passage, ...], question: str
    ) -> str:
        if route == "grounded":
            rendered_evidence = "\n".join(
                _render_evidence_passage(passage) for passage in evidence
            )
            turn_context = f"{self.grounded}\n\nSupporting facts:\n{rendered_evidence}"
        elif route == "insufficient_evidence":
            turn_context = self.insufficient_evidence
        elif route == "privacy_boundary":
            turn_context = self.privacy_boundary
        elif route == "redirected":
            turn_context = self.redirected
        else:
            return question
        return f"{turn_context}\n\nUser question:\n{question}"


def _render_evidence_passage(passage: Passage) -> str:
    section = (
        f" ({' > '.join(passage.section_path)})"
        if passage.section_path and passage.section_path != ("Approved account",)
        else ""
    )
    line = f"-{section} {passage.text}"
    if passage.further_reading:
        links = "; ".join(
            f"{link.label}: {link.url}" for link in passage.further_reading
        )
        line = f"{line}\n  Further reading: {links}"
    return line


@lru_cache(maxsize=8)
def load_prompts(directory: Path = DEFAULT_PROMPT_DIRECTORY) -> PromptSet:
    contents: dict[str, str] = {}
    digest = sha256()
    for name, filename in _PROMPT_FILES.items():
        path = directory / filename
        try:
            content = path.read_text(encoding="utf-8").rstrip("\n")
        except OSError as error:
            raise RuntimeError(f"Required prompt file is unreadable: {path}") from error
        if not content:
            raise RuntimeError(f"Required prompt file is empty: {path}")
        contents[name] = content
        digest.update(filename.encode())
        digest.update(b"\0")
        digest.update(content.encode())
        digest.update(b"\0")

    return PromptSet(
        system=contents["system"],
        grounded=contents["grounded"],
        web_grounded=contents["web_grounded"],
        insufficient_evidence=contents["insufficient_evidence"],
        privacy_boundary=contents["privacy_boundary"],
        redirected=contents["redirected"],
        turn_analysis=contents["turn_analysis"],
        evidence_sufficiency=contents["evidence_sufficiency"],
        revision=digest.hexdigest(),
    )
