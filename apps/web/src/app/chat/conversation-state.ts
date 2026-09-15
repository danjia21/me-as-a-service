export type ChatStreamEvent =
  | {
      type: "message_start";
      conversation_id: string;
      message_id: string;
    }
  | { type: "text_delta"; delta: string }
  | { type: "message_end" }
  | { type: "error"; detail: string };

export type TranscriptMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "pending" | "complete" | "failed";
  retryContent?: string;
};

export type ConversationState = {
  conversationId: string | null;
  draft: string;
  messages: TranscriptMessage[];
  requestState: "idle" | "submitting" | "streaming";
  sessionRestored: boolean;
};

export type ConversationAction =
  | {
      type: "restore";
      conversationId: string;
      messages: TranscriptMessage[];
    }
  | { type: "session_ready" }
  | { type: "draft_changed"; draft: string }
  | {
      type: "turn_started";
      userMessage: TranscriptMessage;
      assistantMessage: TranscriptMessage;
    }
  | { type: "retry_started"; assistantId: string }
  | {
      type: "stream_started";
      conversationId: string;
    }
  | { type: "text_delta"; pendingId: string; delta: string }
  | {
      type: "turn_completed";
      pendingId: string;
    }
  | {
      type: "turn_failed";
      pendingId: string;
      error: string;
      clearConversation: boolean;
    }
  | { type: "stale_conversation_cleared"; pendingId: string }
  | { type: "reset" };

export const CONVERSATION_ID_KEY = "maas_conversation_id";
export const TRANSCRIPT_KEY = "maas_conversation_transcript";

export const initialState: ConversationState = {
  conversationId: null,
  draft: "",
  messages: [],
  requestState: "idle",
  sessionRestored: false,
};

export function conversationReducer(
  state: ConversationState,
  action: ConversationAction,
): ConversationState {
  switch (action.type) {
    case "restore":
      return {
        ...state,
        conversationId: action.conversationId,
        messages: action.messages,
        sessionRestored: true,
      };
    case "session_ready":
      return { ...state, sessionRestored: true };
    case "draft_changed":
      return { ...state, draft: action.draft };
    case "turn_started":
      return {
        ...state,
        draft: "",
        messages: [
          ...state.messages,
          action.userMessage,
          action.assistantMessage,
        ],
        requestState: "submitting",
      };
    case "retry_started":
      return {
        ...state,
        messages: state.messages.map((message) =>
          message.id === action.assistantId
            ? {
                ...message,
                content: "",
                status: "pending",
              }
            : message,
        ),
        requestState: "submitting",
      };
    case "stream_started":
      return {
        ...state,
        conversationId: action.conversationId,
        requestState: "streaming",
      };
    case "text_delta":
      return {
        ...state,
        messages: state.messages.map((message) =>
          message.id === action.pendingId
            ? { ...message, content: message.content + action.delta }
            : message,
        ),
      };
    case "turn_completed":
      return {
        ...state,
        messages: state.messages.map((message) =>
          message.id === action.pendingId
            ? { ...message, status: "complete" }
            : message,
        ),
        requestState: "idle",
      };
    case "turn_failed":
      return {
        ...state,
        conversationId: action.clearConversation ? null : state.conversationId,
        messages: state.messages.map((message) =>
          message.id === action.pendingId
            ? {
                ...message,
                content: action.error,
                status: "failed",
              }
            : message,
        ),
        requestState: "idle",
      };
    case "stale_conversation_cleared": {
      const assistantIndex = state.messages.findIndex(
        (message) => message.id === action.pendingId,
      );
      return {
        ...state,
        conversationId: null,
        messages:
          assistantIndex > 0
            ? state.messages.slice(assistantIndex - 1, assistantIndex + 1)
            : state.messages,
      };
    }
    case "reset":
      return { ...initialState, sessionRestored: state.sessionRestored };
  }
}

export function parseStoredTranscript(
  value: string | null,
): TranscriptMessage[] | null {
  if (!value) return null;

  try {
    const messages: unknown = JSON.parse(value);
    if (
      !Array.isArray(messages) ||
      messages.length === 0 ||
      messages.some(
        (message) =>
          typeof message !== "object" ||
          message === null ||
          !("id" in message) ||
          typeof message.id !== "string" ||
          !("role" in message) ||
          (message.role !== "user" && message.role !== "assistant") ||
          !("content" in message) ||
          typeof message.content !== "string" ||
          !("status" in message) ||
          message.status !== "complete",
      )
    ) {
      return null;
    }
    return (messages as TranscriptMessage[]).map(
      ({ id, role, content, status, retryContent }) => ({
        id,
        role,
        content,
        status,
        retryContent,
      }),
    );
  } catch {
    return null;
  }
}

export function completedTranscript(messages: TranscriptMessage[]) {
  const completed: TranscriptMessage[] = [];
  for (let index = 0; index < messages.length; index += 2) {
    const userMessage = messages[index];
    const assistantMessage = messages[index + 1];
    if (
      userMessage?.role !== "user" ||
      assistantMessage?.role !== "assistant" ||
      assistantMessage.status !== "complete"
    ) {
      break;
    }
    completed.push(userMessage, assistantMessage);
  }
  return completed;
}
