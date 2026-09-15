"""Load and render the chat application's Git-owned prompt templates.

This module discovers Markdown prompts, computes a revision from their exact
contents, and substitutes caller-provided values.
"""

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

DEFAULT_PROMPT_DIRECTORY = Path(__file__).with_name("prompts")


@dataclass(frozen=True)
class PromptTemplates:
    """Provide named templates plus a revision for tracing and deployment."""

    prompts: dict[str, str]
    revision: str

    def render(self, name: str, values: dict[str, str]) -> str:
        """Render one template with values prepared by the application layer.

        Raises:
            KeyError: If ``name`` is not present or a required value is absent.
        """

        try:
            prompt = self.prompts[name]
        except KeyError as error:
            raise KeyError(f"Unknown prompt: {name}") from error
        return prompt.format_map(values)


@lru_cache(maxsize=8)
def load_prompts(directory: Path = DEFAULT_PROMPT_DIRECTORY) -> PromptTemplates:
    """Load every Markdown prompt in a directory and hash the loaded set.

    Filenames without ``.md`` become prompt names. Sorting makes the revision
    stable regardless of filesystem order. Empty or unreadable prompt sets fail
    during application construction.
    """

    prompts: dict[str, str] = {}
    digest = sha256()
    for path in sorted(directory.glob("*.md")):
        try:
            content = path.read_text(encoding="utf-8").rstrip("\n")
        except OSError as error:
            raise RuntimeError(f"Prompt file is unreadable: {path}") from error
        if not content:
            raise RuntimeError(f"Prompt file is empty: {path}")
        prompts[path.stem] = content
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(content.encode())
        digest.update(b"\0")

    if not prompts:
        raise RuntimeError(f"No Markdown prompt files found in: {directory}")

    return PromptTemplates(prompts=prompts, revision=digest.hexdigest())
