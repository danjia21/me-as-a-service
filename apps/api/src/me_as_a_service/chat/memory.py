"""Bridge persisted conversation history and bounded model context.

This module loads raw session messages, keeps the newest complete turns within
count and character limits, and appends completed turns to a supplied store.
"""

from uuid import UUID

from .storage import ConversationStore
from .types import MAX_PAST_TURNS, ConversationContext, StoredMessage

DEFAULT_CONTEXT_CHARACTER_LIMIT = 12_000


class ChatMemory:
    """Provide bounded session context over a conversation store."""

    def __init__(self, store: ConversationStore) -> None:
        """Use ``store`` as the sole source and sink for conversation history."""

        self._store = store

    @property
    def store(self) -> ConversationStore:
        """Expose the configured store for conversation lifecycle operations."""

        return self._store

    async def initialize(self) -> None:
        """Initialize storage required by conversation memory."""

        await self._store.initialize()

    async def healthcheck(self) -> None:
        """Verify that the conversation store is available."""

        await self._store.healthcheck()

    async def assemble_context(
        self,
        conversation_id: UUID,
        current_message: StoredMessage,
        *,
        past_turn_limit: int = MAX_PAST_TURNS,
        character_limit: int = DEFAULT_CONTEXT_CHARACTER_LIMIT,
    ) -> ConversationContext:
        """Build model context from bounded history and the current message.

        Selection keeps whole prior turns, newest first, under both limits.
        """

        if past_turn_limit < 0 or character_limit < 1:
            raise ValueError("context limits must be positive")

        # Get conversation history, capped at past_turn_limit and character_limit
        stored_history = await self._store.history(conversation_id)
        prior_turns = tuple(
            stored_history[index : index + 2]
            for index in range(0, len(stored_history), 2)
        )
        candidate_turns = prior_turns[-past_turn_limit:] if past_turn_limit else ()
        selected_turns: list[tuple[StoredMessage, ...]] = []
        character_count = len(current_message.content)
        for turn in reversed(candidate_turns):
            turn_length = sum(len(message.content) for message in turn)
            if character_count + turn_length > character_limit:
                break
            selected_turns.append(turn)
            character_count += turn_length

        # Assemble ConversationContext
        selected_messages = tuple(
            message for turn in reversed(selected_turns) for message in turn
        )

        return ConversationContext(
            messages=(*selected_messages, current_message),
            completed_turns=len(stored_history) // 2,
        )

    async def append_turn(
        self,
        conversation_id: UUID,
        user_message: StoredMessage,
        assistant_message: StoredMessage,
    ) -> None:
        """Persist one completed user-and-assistant turn atomically via the store."""

        await self._store.append_turn(
            conversation_id,
            user_message,
            assistant_message,
        )
