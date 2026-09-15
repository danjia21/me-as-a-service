import { type ReactNode, type RefObject } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { OutboundIcon } from "./chat-icons";
import { ConversationState, TranscriptMessage } from "./conversation-state";
import styles from "./chat-transcript.module.css";

const ALLOWED_MARKDOWN_ELEMENTS = [
  "p",
  "strong",
  "em",
  "ul",
  "ol",
  "li",
  "h2",
  "h3",
  "code",
  "pre",
  "br",
  "a",
];

function compactLinkDestination(url: string) {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.replace(/^www\./, "");
    const path = parsed.pathname.replace(/\/$/, "");
    return `${host}${path}`;
  } catch {
    return url;
  }
}

function linkPresentation(children: ReactNode, href = "") {
  if (typeof children !== "string") {
    return { label: children, destination: null };
  }

  const destination = compactLinkDestination(href);
  if (/^(?:https?:\/\/|www\.)/i.test(children)) {
    return { label: null, destination };
  }

  const isGenericLabel = /^(?:github|link|source|website|here)$/i.test(
    children.trim(),
  );
  return {
    label: children,
    destination: isGenericLabel ? destination : null,
  };
}

type ChatTranscriptProps = {
  messages: TranscriptMessage[];
  requestState: ConversationState["requestState"];
  speakerName: string;
  transcriptRef: RefObject<HTMLDivElement | null>;
  onRetry: (message: TranscriptMessage) => void;
  onScroll: () => void;
};

export function ChatTranscript({
  messages,
  requestState,
  speakerName,
  transcriptRef,
  onRetry,
  onScroll,
}: ChatTranscriptProps) {
  const initials = speakerName
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <div className={styles.transcript} onScroll={onScroll} ref={transcriptRef}>
      {messages.map((message) =>
        message.role === "user" ? (
          <article className={styles.userTurn} key={message.id}>
            <p>{message.content}</p>
          </article>
        ) : (
          <article
            aria-busy={message.status === "pending"}
            aria-live="polite"
            className={`${styles.assistantTurn} ${
              message.status === "failed" ? styles.failedTurn : ""
            }`}
            key={message.id}
          >
            <div className={styles.assistantAvatar} aria-hidden="true">
              {initials}
            </div>
            <div className={styles.turnBody}>
              {message.status === "pending" && !message.content ? (
                <p className={styles.pendingText}>Thinking…</p>
              ) : (
                <div className={styles.markdown}>
                  <ReactMarkdown
                    allowedElements={ALLOWED_MARKDOWN_ELEMENTS}
                    components={{
                      a: ({ children, href }) => {
                        const link = linkPresentation(children, href);
                        return (
                          <a
                            href={href}
                            rel="noreferrer"
                            target="_blank"
                            title={href}
                          >
                            {link.label ? <span>{link.label}</span> : null}
                            {link.destination ? (
                              <span className={styles.markdownLinkDestination}>
                                {link.destination}
                              </span>
                            ) : null}
                            <OutboundIcon className={styles.markdownLinkIcon} />
                          </a>
                        );
                      },
                    }}
                    remarkPlugins={[remarkGfm]}
                    skipHtml
                    unwrapDisallowed
                  >
                    {message.content}
                  </ReactMarkdown>
                </div>
              )}
              {message.status === "failed" ? (
                <button
                  className={styles.retry}
                  disabled={requestState !== "idle"}
                  onClick={() => onRetry(message)}
                  type="button"
                >
                  Retry this response
                </button>
              ) : null}
            </div>
          </article>
        ),
      )}
    </div>
  );
}
