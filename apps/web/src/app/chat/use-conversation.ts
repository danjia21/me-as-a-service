"use client";

import { useEffect, useReducer } from "react";
import {
  ChatStreamEvent,
  completedTranscript,
  CONVERSATION_ID_KEY,
  conversationReducer,
  initialState,
  parseFurtherReading,
  parseStoredTranscript,
  TRANSCRIPT_KEY,
  TranscriptMessage,
} from "./conversation-state";

function clearStoredConversation() {
  sessionStorage.removeItem(CONVERSATION_ID_KEY);
  sessionStorage.removeItem(TRANSCRIPT_KEY);
}

export function useConversation() {
  const [state, dispatch] = useReducer(conversationReducer, initialState);

  useEffect(() => {
    const conversationId = sessionStorage.getItem(CONVERSATION_ID_KEY);
    const messages = parseStoredTranscript(
      sessionStorage.getItem(TRANSCRIPT_KEY),
    );
    if (conversationId && messages) {
      dispatch({ type: "restore", conversationId, messages });
    } else {
      clearStoredConversation();
      dispatch({ type: "session_ready" });
    }
  }, []);

  useEffect(() => {
    if (!state.sessionRestored) return;

    if (!state.conversationId) {
      clearStoredConversation();
      return;
    }

    const messages = completedTranscript(state.messages);
    if (messages.length > 0) {
      sessionStorage.setItem(CONVERSATION_ID_KEY, state.conversationId);
      sessionStorage.setItem(TRANSCRIPT_KEY, JSON.stringify(messages));
    }
  }, [state.conversationId, state.messages, state.sessionRestored]);

  async function requestTurn(
    content: string,
    pendingId: string,
    conversationId: string | null,
  ) {
    try {
      function postMessage(activeConversationId: string | null) {
        return fetch("/api/chat", {
          method: "POST",
          headers: {
            Accept: "application/x-ndjson",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            conversation_id: activeConversationId,
            message: content,
          }),
        });
      }

      let response = await postMessage(conversationId);
      if (response.status === 404 && conversationId) {
        clearStoredConversation();
        dispatch({ type: "stale_conversation_cleared", pendingId });
        response = await postMessage(null);
      }

      if (!response.ok) {
        const body: unknown = await response.json();
        const detail =
          typeof body === "object" &&
          body !== null &&
          "detail" in body &&
          typeof body.detail === "string"
            ? body.detail
            : "The interview agent could not answer that message.";
        throw Object.assign(new Error(detail), {
          clearConversation: response.status === 404,
        });
      }

      if (!response.body) {
        throw new Error("The interview agent returned an empty response.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;

      function consumeLine(line: string) {
        if (!line.trim()) return;
        const event = JSON.parse(line) as ChatStreamEvent;

        switch (event.type) {
          case "message_start":
            sessionStorage.setItem(CONVERSATION_ID_KEY, event.conversation_id);
            dispatch({
              type: "stream_started",
              conversationId: event.conversation_id,
            });
            break;
          case "text_delta":
            dispatch({ type: "text_delta", pendingId, delta: event.delta });
            break;
          case "further_reading": {
            const links = parseFurtherReading(event.links);
            if (links) {
              dispatch({ type: "further_reading", pendingId, links });
            }
            break;
          }
          case "message_end":
            completed = true;
            dispatch({
              type: "turn_completed",
              pendingId,
            });
            break;
          case "error":
            throw new Error(event.detail);
        }
      }

      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        lines.forEach(consumeLine);
        if (done) break;
      }
      consumeLine(buffer);

      if (!completed) {
        throw new Error(
          "The response stream ended before the answer completed.",
        );
      }
    } catch (requestError) {
      const clearConversation =
        requestError instanceof Error &&
        "clearConversation" in requestError &&
        requestError.clearConversation === true;
      if (clearConversation) clearStoredConversation();
      dispatch({
        type: "turn_failed",
        pendingId,
        error:
          requestError instanceof Error
            ? requestError.message
            : "The interview agent could not answer that message.",
        clearConversation,
      });
    }
  }

  function setDraft(draft: string) {
    dispatch({ type: "draft_changed", draft });
  }

  async function submitMessage() {
    const content = state.draft.trim();
    if (!content || state.requestState !== "idle") return;

    const pendingId = crypto.randomUUID();
    dispatch({
      type: "turn_started",
      userMessage: {
        id: crypto.randomUUID(),
        role: "user",
        content,
        status: "complete",
      },
      assistantMessage: {
        id: pendingId,
        role: "assistant",
        content: "",
        status: "pending",
        retryContent: content,
      },
    });
    await requestTurn(content, pendingId, state.conversationId);
  }

  async function retryMessage(message: TranscriptMessage) {
    if (!message.retryContent || state.requestState !== "idle") return;
    dispatch({ type: "retry_started", assistantId: message.id });
    await requestTurn(message.retryContent, message.id, state.conversationId);
  }

  function startNewConversation() {
    clearStoredConversation();
    dispatch({ type: "reset" });
  }

  return {
    state,
    setDraft,
    submitMessage,
    retryMessage,
    startNewConversation,
  };
}
