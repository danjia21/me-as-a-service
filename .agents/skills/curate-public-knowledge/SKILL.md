---
name: curate-public-knowledge
description: Convert reviewed public-evidence research ledgers (produced by bootstrap-public-knowledge) into curated, question-focused Markdown under an instance's knowledge/public/ directory by fetching each source and rewriting the relevant portion, with explicit user review. Use when a user wants to turn workspace/research/*.yaml ledger results into authoritative public knowledge, review pending research results for acceptance or rejection, or publish accepted public evidence into the retrieval corpus.
---

# Curate Public Knowledge

Turn accepted results from public-evidence research ledgers into curated
Markdown that is safe to enter the retrieval corpus, without silently
promoting unreviewed or rejected material. This skill is the review-and-curate
step described by `bootstrap-public-knowledge`; run that skill first if the
research ledgers do not exist yet.

## Prepare

1. Resolve the instance directory from an explicitly supplied path or
   `MAAS_INSTANCE_DIR`. Ask only when neither identifies the intended
   instance.
2. Read `<instance>/instance.yaml`, every ledger under
   `<instance>/workspace/research/*.yaml` except `queue.yaml`, and any
   existing files under `<instance>/knowledge/public/`.
3. Read
   [public-knowledge-schema.md](references/public-knowledge-schema.md)
   before creating or updating a public knowledge document.
4. Group ledger results by `topic_id`. Skip a ledger entirely if it has no
   `pending` results and every accepted result already appears in some
   existing `knowledge/public/<topic-id>-*.md` file — there is nothing new
   to draft.

## Review one topic cluster at a time

1. Select one ledger topic with `pending` results.
2. For each pending result, show the user: the source title, URL, publisher,
   source kind, authority, the `direct_support` claims, and any
   `limitations`. Keep `inference_notes` visible too, but label them clearly
   as interpretation, not fact.
3. Ask the user to accept or reject each result. Accepting a whole topic in
   one pass is fine when the user says so explicitly; do not assume it.
4. Record the decision by setting `review_status` to `accepted` or `rejected`
   directly in `<instance>/workspace/research/<topic-id>.yaml`. Change
   nothing else in the ledger. Leave already-`accepted` or already-`rejected`
   results untouched unless the user asks to revisit one.
5. If the user wants to soften an overstated claim, edit the claim wording
   only if the user directs the edit; do not rewrite `direct_support` on your
   own judgment beyond fixing the boundary issues described below.

Do not accept a result whose `direct_support` claims assert the person's
private motivation, individual responsibility, decision process, or
confidential work — a public source can corroborate public facts but cannot
by itself establish those. Flag such results to the user and suggest routing
that material through the personal-knowledge interview process instead of
accepting it here.

## Choose the questions a topic answers

1. Once a topic has accepted results, judge — from what those sources
   actually establish, not from a fixed checklist — which distinct questions
   a visitor could plausibly ask that this evidence can answer. A typical
   publication topic yields questions like what the work is and how it
   works, what results it publicly reports, where and when it was published,
   and how it was deployed or received; a thinner topic may only support one
   question, and that is fine.
2. Do not force every accepted source into its own file, and do not force
   every topic into the same fixed set of angles. One question can draw on
   several sources; one source can inform several questions.
3. Prefer splitting over cramming: if answering a question well requires
   pulling in a tangential fact, that fact likely belongs in its own file
   instead.

## Fetch each source and draft one file per question

1. For each planned question file, fetch and actually read every source URL
   it depends on — the ledger's `direct_support` claims are a verified index
   of what a source supports, not a substitute for reading it. Pull the
   specific detail that answers this question; for a long source, extract
   only the relevant portion rather than summarizing the whole thing.
2. Draft `<instance>/knowledge/public/<topic-id>-<question-slug>.md`
   following
   [public-knowledge-schema.md](references/public-knowledge-schema.md):
   scalar front matter with `id` and `title` only, then a rewritten,
   third-person synthesis answering the question in your own words — never
   paste paragraphs, transcribe figures, or reproduce code — followed by a
   `## Further reading` section listing only the source(s) this specific
   file drew on as `Label: https://url` list items.
3. If a source is unreachable when drafting, fall back to the ledger's
   recorded claims for that fact and say so plainly to the user rather than
   presenting it as freshly verified.
4. Before writing, check that the chosen `id` does not collide with any
   existing source id under `<instance>/knowledge/`. Disambiguate on
   collision instead of overwriting an unrelated document.
5. If a question file already exists from an earlier run and new accepted
   sources materially add to its answer, revise it in place rather than
   creating a near-duplicate file. Never remove existing accepted content
   because of this run alone; only remove it when the user explicitly asks.
6. Show the user each drafted file before writing it — this is the final
   gate before the material becomes retrievable knowledge. A clear
   affirmative such as "looks good" or "approved" counts as approval; revise
   and re-show on any corrective feedback. Batching several files for one
   approval pass is fine when the user prefers that.
7. On approval, write the file(s) under `<instance>/knowledge/public/`.

## Validate

1. Validate the new or changed document with the repository's Markdown
   source loader or closest available check (for example the API's
   `load_markdown_source`/`load_markdown_corpus` or its test suite),
   confirming the `## Further reading` entries parse into structured links
   and are absent from the passage text. Report any validation failure and
   repair only the document this task changed.
2. Validate the edited ledger YAML with the repository's closest available
   parser. Repair only the records this task changed.

## Keep the corpus boundary intact

Directory placement is the publication boundary: only documents under
`<instance>/knowledge/` (including `knowledge/public/`) are approved and
eligible for retrieval. Ledgers and the queue under
`<instance>/workspace/research/` stay external evidence and never enter
runtime retrieval on their own, no matter how many results they contain.

Never write a document under `knowledge/public/` from a `pending` or
`rejected` result. Never use the `# Approved account` or `## Experience`
headings in a public document — those are reserved markers the loader uses to
parse personal accounts and profile records; a public document that used them
would be silently parsed as the wrong kind of source.

## Stop and resume

Stop when the user pauses or stops, when every ledger's results are reviewed
and every accepted result is curated into some question file, or when a real
blocker prevents further progress. After each topic, give a short progress
update: reviewed count, accepted count, rejected count, and the question
files written or updated.

On the next invocation, reconstruct state from `review_status` values in the
ledgers and from existing files under `knowledge/public/` rather than
assuming prior chat history is available, then continue with the next topic
that still has pending results or accepted results not yet reflected in any
file.
