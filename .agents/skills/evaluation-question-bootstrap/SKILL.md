---
name: evaluation-question-bootstrap
description: Bootstrap or expand an instance's evaluations/questions.yaml from its curated public knowledge. Use when a Me-as-a-Service instance needs hand-reviewed router, retrieval, citation, abstention, follow-up, or scope-boundary evaluation cases, especially when its optional fixture is absent.
---

# Evaluation Question Bootstrap

Create an optional, versioned `<instance>/evaluations/questions.yaml` fixture
grounded in the selected instance's curated knowledge.

Read [the fixture schema](references/evaluation-schema.md) completely before
editing.

1. Resolve the instance directory from an explicitly supplied path or
   `MAAS_INSTANCE_DIR`. Ask only when neither identifies the intended instance.
2. Inspect `<instance>/instance.yaml`, the repository's evaluation loader,
   tests, `<instance>/knowledge/`, and the existing fixture when present. Treat
   implementation contracts as authoritative for field names and allowed
   values.
3. Draft 20–40 compact cases spanning direct facts, multi-source synthesis,
   contextual follow-ups, corrections, low-overlap wording, unsupported
   premises, social turns, unrelated requests, and adversarial scope shifts.
4. Verify every personal fact, expected source, and relevant section directly
   against the curated source. Remove unsupported claims. Never use visitor
   messages, model output, private notes, or undocumented memory as evidence.
5. Assign the expected route and citation behavior independently of the
   current router's prediction. Keep failures as a worklist; do not weaken
   expected behavior to make tests pass.
6. Write or extend `<instance>/evaluations/questions.yaml`. Preserve stable case
   IDs and reviewed cases unless the underlying source or product contract
   changed.
7. Run the fixture validation, routing/retrieval tests, and
   `pnpm eval:routing` when available. Report coverage gaps and cases that still
   need human review.

Do not write model-generated gold answers or assert exact hosted-model wording.
Required facts are evidence expectations for later evaluation, not permission
to invent an answer.
