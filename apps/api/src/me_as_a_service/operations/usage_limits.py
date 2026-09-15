"""Enforce conversational turn limits and aggregate token budgets."""

from datetime import UTC, datetime

from .token_usage import UsageLedger

DEFAULT_MAX_TURNS_PER_CONVERSATION = 20
DEFAULT_DAILY_TOKEN_BUDGET = 100_000


class UsageLimitExceeded(RuntimeError):
    pass


class UsageLimits:
    """Reject turns that exceed conversation or daily model-use limits."""

    def __init__(
        self,
        usage_ledger: UsageLedger,
        *,
        max_turns_per_conversation: int = DEFAULT_MAX_TURNS_PER_CONVERSATION,
        daily_token_budget: int = DEFAULT_DAILY_TOKEN_BUDGET,
    ) -> None:
        if max_turns_per_conversation < 1:
            raise ValueError("max_turns_per_conversation must be positive")
        if daily_token_budget < 1:
            raise ValueError("daily_token_budget must be positive")
        self._usage_ledger = usage_ledger
        self._max_turns_per_conversation = max_turns_per_conversation
        self._daily_token_budget = daily_token_budget

    @property
    def daily_token_budget(self) -> int:
        return self._daily_token_budget

    async def check(self, completed_turns: int) -> None:
        if completed_turns >= self._max_turns_per_conversation:
            raise UsageLimitExceeded(
                "This conversation reached its turn limit. Start a new conversation."
            )
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        if await self._usage_ledger.tokens_since(today) >= self._daily_token_budget:
            raise UsageLimitExceeded(
                "The daily model budget is exhausted. Please try again tomorrow."
            )
