# Personal knowledge storage schema

Adapt paths to repository conventions, but keep approved autobiographical
sources and coverage state separate.

## Approved personal source

Create one file per approved canonical account. Prefer a project-level account
or coherent topic slice over one file per coaching prompt:

`<instance>/knowledge/personal/<stable-topic-id>.md`

Use only metadata accepted by the repository's source loader. The current
Me-as-a-Service loader accepts scalar front matter with these fields:

```markdown
---
id: search-platform-architecture
title: Architecture of the search platform
---

# Interview question

What decisions, outcomes, and lessons best explain how you built and evolved the model-serving platform?

# Approved account

The user-approved first-person account goes here.

# Evidence boundaries

- Exact adoption numbers were not recorded.
- Customer and internal system names are intentionally omitted.
```

The question may be a batch intake spanning several related coverage gaps. It
must be the exact primary question the user answered, not a list of coach
prompts or a reconstructed question.

An approved account goes directly under `<instance>/knowledge/personal/` after
the existing approval and is eligible for retrieval. Use
`<instance>/workspace/drafts/` only when the user asks to save a draft or the
process is interrupted after an editor draft exists. Drafts are not
authoritative sources and must not be ingested. Keep list items on one line for
compatibility with the strict Markdown loader.

Do not rewrite or combine existing approved files as part of ordinary capture.
Treat consolidation as a separate user-approved migration.

Do not add guessed dates, tags, arrays, URLs, or other front-matter fields when
the loader rejects them. Put necessary human-readable context in the body or
extend the application schema as a separate, tested change.

## Coverage registry

Store resumable process state in:

`<instance>/workspace/coverage.yaml`

Recommended shape:

```yaml
version: 1
seed_sources:
  - resume
topics:
  - id: search-platform
    source_refs:
      - resume
    angles:
      context: approved
      ownership: approved
      constraints: approved
      decisions: partial
      alternatives: missing
      trade_offs: partial
      failures: missing
      collaboration: missing
      outcomes: approved
      lessons: missing
      current_reflection: missing
    approved_note_ids:
      - search-platform-architecture
    asked_questions:
      - What decisions, outcomes, and lessons best explain how you built and evolved the model-serving platform?
    next_question_hint: What alternatives were considered and rejected?
```

Use the statuses `missing`, `partial`, and `approved`. Treat semantic duplicates
as the same question even when wording differs. Keep exact asked questions for
auditability. A batch intake can advance several angles, but mark each angle
from the evidence actually present in the approved account. Do not mark all
prompted dimensions approved merely because the user received prompts for them.

If the repository has a different validated registry schema, use it instead.
