"use client";

import { useEffect, useRef, useState } from "react";
import { ChatComposer } from "./chat/chat-composer";
import { GitHubIcon, MarkIcon, PromptArrowIcon } from "./chat/chat-icons";
import { ChatTranscript } from "./chat/chat-transcript";
import { type TranscriptMessage } from "./chat/conversation-state";
import { useConversation } from "./chat/use-conversation";
import { type PublicInstanceConfig } from "../instance";
import styles from "./chat-workspace.module.css";

type ChatWorkspaceProps = {
  instance: PublicInstanceConfig;
};

export function ChatWorkspace({ instance }: ChatWorkspaceProps) {
  const { state, setDraft, submitMessage, retryMessage, startNewConversation } =
    useConversation();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const shouldStickToBottomRef = useRef(true);
  const hasMessages = state.messages.length > 0;
  const repositoryLabel = instance.links.repository?.replace(
    /^https?:\/\/github\.com\//,
    "",
  );
  const [pageViews, setPageViews] = useState<number | "unavailable" | null>(
    null,
  );

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/traffic", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Traffic request failed");
        const data = (await response.json()) as {
          page_views?: unknown;
          period_days?: unknown;
        };
        if (typeof data.page_views !== "number" || data.period_days !== 7) {
          throw new Error("Invalid traffic response");
        }
        setPageViews(data.page_views);
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setPageViews("unavailable");
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (shouldStickToBottomRef.current && transcript) {
      transcript.scrollTop = transcript.scrollHeight;
    }
  }, [state.messages]);

  function chooseQuestion(suggestion: string) {
    setDraft(suggestion);
    textareaRef.current?.focus();
  }

  function handleTranscriptScroll() {
    const transcript = transcriptRef.current;
    if (!transcript) return;
    const distanceFromBottom =
      transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight;
    shouldStickToBottomRef.current = distanceFromBottom < 120;
  }

  function handleSubmit() {
    shouldStickToBottomRef.current = true;
    void submitMessage().finally(() =>
      requestAnimationFrame(() => textareaRef.current?.focus()),
    );
  }

  function handleRetry(message: TranscriptMessage) {
    shouldStickToBottomRef.current = true;
    void retryMessage(message).finally(() =>
      requestAnimationFrame(() => textareaRef.current?.focus()),
    );
  }

  function handleNewConversation() {
    startNewConversation();
    requestAnimationFrame(() => textareaRef.current?.focus());
  }

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <a
          className={styles.brand}
          href="#top"
          aria-label="Me-as-a-Service home"
        >
          <span className={styles.mark}>
            <MarkIcon />
          </span>
          <span className={styles.brandCopy}>
            <strong>Me-as-a-Service</strong>
            <span className={styles.tagline}>
              Because my résumé doesn&apos;t answer follow-up questions.
            </span>
          </span>
        </a>

        {hasMessages ? (
          <div className={styles.headerActions}>
            <button
              className={styles.newConversation}
              onClick={handleNewConversation}
              type="button"
            >
              New chat
            </button>
          </div>
        ) : null}
      </header>

      <section className={styles.workspace} id="top">
        <div
          className={`${styles.conversation} ${
            hasMessages ? styles.conversationActive : ""
          }`}
        >
          {!hasMessages ? (
            <div className={styles.welcome}>
              <span className={styles.heroMark}>
                <MarkIcon />
              </span>
              <h1>Hi, I&apos;m {instance.display_name}.</h1>
              <p>
                Ask me about the systems I&apos;ve built, my research, or how I
                approach engineering decisions.
              </p>
              <div
                className={styles.promptGrid}
                aria-label="Suggested questions"
              >
                {instance.suggested_questions.map((question) => (
                  <button
                    className={styles.promptCard}
                    disabled={state.requestState !== "idle"}
                    key={question}
                    onClick={() => chooseQuestion(question)}
                    type="button"
                  >
                    <span>{question}</span>
                    <PromptArrowIcon className={styles.promptArrow} />
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {hasMessages ? (
            <ChatTranscript
              messages={state.messages}
              onRetry={handleRetry}
              onScroll={handleTranscriptScroll}
              requestState={state.requestState}
              speakerName={instance.display_name}
              transcriptRef={transcriptRef}
            />
          ) : null}

          <ChatComposer
            draft={state.draft}
            hasMessages={hasMessages}
            onDraftChange={setDraft}
            onSubmit={handleSubmit}
            requestState={state.requestState}
            subjectName={instance.display_name}
            textareaRef={textareaRef}
          />
        </div>
      </section>

      <footer className={styles.footer}>
        <p>
          This is an AI representation of a person, not the real person. AI can
          make mistakes. Verify important details independently.
        </p>
        <div className={styles.footerLinks}>
          {instance.links.repository ? (
            <a
              href={instance.links.repository}
              rel="noreferrer"
              target="_blank"
            >
              <GitHubIcon />
              {repositoryLabel}
            </a>
          ) : null}
          <span aria-live="polite">
            {typeof pageViews === "number"
              ? `${pageViews.toLocaleString()} ${
                  pageViews === 1 ? "visit" : "visits"
                } in the last 7 days`
              : pageViews === "unavailable"
                ? "Visits unavailable"
                : "Loading visits…"}
          </span>
        </div>
      </footer>
    </main>
  );
}
