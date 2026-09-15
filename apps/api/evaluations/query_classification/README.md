# Query classification evaluation

This live evaluation contains ten frozen, fictional cases for each
`ConversationType`. It renders the production classifier prompt with the neutral
display name `Alex Example` and calls the configured hosted model directly. It does
not load an instance, search a knowledge index, or generate chat responses.

Run it explicitly from the repository root:

```sh
pnpm --filter @me-as-a-service/api eval:classification
```

The command loads provider settings from the environment or the repository `.env`.
It makes 50 billable model requests and is intentionally excluded from the default
test suite. LangSmith tracing is explicitly disabled because the results are intended
for direct inspection. Each `evidence_required` result must contain a nonblank
rewritten query; every other result must contain a null query, as enforced by
`MessageClassification`.
