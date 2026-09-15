# Retrieval-free response evaluation

This live evaluation contains ten frozen, fictional cases for each retrieval-free
`ConversationType`: `conversation`, `irrelevant`, `discuss_in_person`, and
`inappropriate`. It selects the generation prompt directly from each case's
ground-truth type, renders it with the dummy display name `Alex Example`, and prints
the query and response for manual review. Cases run sequentially, and each response
is streamed to the terminal before the next request starts.

Run it explicitly from the repository root:

```sh
pnpm --filter @me-as-a-service/api eval:retrieval-free-response
```

The command loads provider settings from the environment or repository `.env`, makes
up to 40 billable model requests, and is excluded from the default test suite. To run
only selected response types, comment out entries in `KEPT_CONVERSATION_TYPES` near
the top of the test file. It does not classify messages, retrieve documents, rate
response quality, or enable LangSmith tracing. Provider failures still fail the run
because they leave cases without a response.
