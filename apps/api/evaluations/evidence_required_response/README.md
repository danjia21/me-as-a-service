# Evidence-required response evaluation

This live evaluation loads 10 standalone questions from the selected instance's
`evaluations/evidence_required.json` file. Every question is expected to require
retrieval from that instance's knowledge index.

For each question, the evaluation uses `ChatWorkflow` to run the complete production
turn, including classification, retrieval when requested, and response generation. It
prints the question and final model response only. Classification results, retrieval
queries, and retrieved documents are deliberately omitted.

Run it explicitly from the repository root:

```sh
pnpm --filter @me-as-a-service/api eval:evidence-required-response
```

The command loads `MAAS_INSTANCE_DIR` and provider settings from the environment or
the repository `.env`. Cases run sequentially and make up to 20 billable model
requests: one classification and one response request per question. LangSmith tracing
is disabled. An invalid question file or provider failure fails the run; provider
failures are collected so all possible cases can still be printed.
