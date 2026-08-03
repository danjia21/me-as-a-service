import { FormEvent, KeyboardEvent, RefObject, useEffect, useId } from "react";
import { ArrowIcon } from "./chat-icons";
import { ConversationState } from "./conversation-state";
import styles from "./chat-composer.module.css";

type ChatComposerProps = {
  draft: string;
  hasMessages: boolean;
  requestState: ConversationState["requestState"];
  subjectName: string;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  onDraftChange: (draft: string) => void;
  onSubmit: () => void;
};

export function ChatComposer({
  draft,
  hasMessages,
  requestState,
  subjectName,
  textareaRef,
  onDraftChange,
  onSubmit,
}: ChatComposerProps) {
  const textareaId = useId();

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
  }, [draft, textareaRef]);

  function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <form
      aria-busy={requestState !== "idle"}
      className={`${styles.composer} ${
        hasMessages ? styles.conversationActive : ""
      }`}
      onSubmit={submitMessage}
    >
      <label htmlFor={textareaId}>Ask a question about {subjectName}</label>
      <div className={styles.composerBody}>
        <textarea
          id={textareaId}
          disabled={requestState !== "idle"}
          onChange={(event) => onDraftChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            hasMessages ? "Ask a follow-up…" : "Ask me about my work…"
          }
          ref={textareaRef}
          rows={1}
          value={draft}
        />
        <button
          className={styles.submit}
          disabled={!draft.trim() || requestState !== "idle"}
          aria-label="Send message"
          type="submit"
        >
          <ArrowIcon />
        </button>
      </div>
      <div className={styles.composerMeta}>
        <span>Enter to send · Shift+Enter for a new line</span>
      </div>
    </form>
  );
}
