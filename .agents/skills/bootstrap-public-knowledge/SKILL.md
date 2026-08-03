---
name: bootstrap-public-knowledge
description: Bootstrap a structured public knowledge corpus about a person's documented work through exhaustive public-evidence discovery, source assessment, provenance, and explicit review boundaries. Use when a user wants to expand a résumé or seed document with public evidence from publications, repositories, benchmarks, awards, workshops, project pages, employers, or named technologies; wants resumable public-evidence queues or ledgers; or wants public corroboration kept separate from autobiographical claims.
---

# Bootstrap Public Knowledge

Discover externally verifiable claims without turning search results, summaries,
or inferences into evidence of private experience. Continue autonomously until
the bounded public-evidence queue is exhausted; do not ask the user to confirm
each topic or batch.

## Prepare

1. Resolve the instance directory from an explicitly supplied path or
   `MAAS_INSTANCE_DIR`. Ask only when neither identifies the intended instance.
2. Read repository guidance, `<instance>/instance.yaml`, seed material under
   `<instance>/inputs/`, existing research ledgers, and relevant approved
   knowledge notes.
3. Store research ledgers under
   `<instance>/workspace/research/<topic-id>.yaml`.
4. Read
   [public-evidence-ledger-schema.md](references/public-evidence-ledger-schema.md)
   before creating or updating a ledger.
5. Build a queue from every concrete public lead in the seed and discovered
   sources: publications, repositories, benchmarks, awards, workshops, official
   project pages, employers, named projects, and distinctive technologies.
6. Track each lead as pending, completed, pruned, or blocked. Record why a lead
   is pruned or blocked so later runs do not repeat it.
7. Group related leads into named topic clusters and write the initial queue to
   `<instance>/workspace/research/queue.yaml`.
8. Before searching, show the user the complete initial cluster list, the total
   cluster count, and the processing order. Make clear that discovery can add
   clusters later and that work will continue automatically.

## Define the evidence boundary

Use public evidence to corroborate public facts or supply external context.
Never use it alone to establish the person's private motivation, individual
responsibility, decision process, personal opinion, or confidential work.

Do not silently import personal, sensitive, paywalled, access-controlled, or
confidential information merely because it is discoverable. Keep public
research separate from approved autobiographical sources and from derived claim
or passage indexes.

## Process the full evidence queue

1. Select one coherent, high-value topic cluster. Avoid searches that mix
   unrelated entities or make provenance hard to audit.
2. Start with precise queries grounded in named entities from the seed source
   or previously inspected sources.
3. Prefer primary sources: papers, proceedings, official repositories, official
   project pages, standards, and official announcements.
4. Use secondary sources only when they add necessary context or when no primary
   source is available. Label their authority accurately.
5. Open and inspect the supporting page; do not treat a search-result snippet as
   evidence.
6. For every result, record the query, canonical URL, title, publisher,
   retrieval date, source kind, authority, related entities, direct support,
   inference notes, limitations, review state, and licensing notes when
   relevant.
7. Write `direct_support` as concise paraphrased atomic claims. Put all
   interpretation in `inference_notes`.
8. Deduplicate tracking URLs, mirrors, and repeated content in favor of the
   canonical source. Preserve credible conflicts and describe them rather than
   silently choosing a winner.
9. Add newly discovered concrete leads to the queue.
10. Save progress after each coherent batch so another session can resume from
    repository state rather than chat history.
11. Update `queue.yaml` after each cluster and whenever discovery adds, merges,
    prunes, or blocks a cluster.
12. Send the user a concise progress update after each cluster, including the
    completed count, current total, cluster name, result count, meaningful
    conflicts or limitations, newly discovered clusters, and next cluster.
13. Continue immediately with the next cluster. Do not pause for approval,
    review, or confirmation between clusters.

Progress updates are informational checkpoints, not questions. Do not ask
whether to continue unless new authority or a disclosure-boundary decision is
genuinely required.

## Decide when discovery is complete

Treat discovery as bounded to public evidence about the person's documented
work, not all general information about every employer or technology mentioned.
The queue is exhausted only when:

- every concrete lead from the seed and inspected sources is completed, pruned,
  or blocked;
- exact-title, author, project, repository, award, benchmark, and official-site
  searches no longer reveal new relevant artifacts;
- citation trails and official outbound links from the strongest sources have
  been checked for additional relevant primary artifacts; and
- the remaining results are duplicates, generic background, unrelated people
  with similar names, inaccessible sources, or evidence outside the disclosure
  boundary.

Do not interpret a temporary lack of search results for one query as
exhaustion. Try reasonable query variants and authoritative indexes before
marking a lead blocked.

## Assess and report

Distinguish clearly among:

- what a source states directly;
- what multiple sources jointly support;
- what is an inference;
- what remains unknown or disputed.

Use citations in the user-facing research summary. Note meaningful source
limitations, ambiguity in identity or authorship, stale information, and any
claim that still needs confirmation.

Do not overstate authorship, ownership, adoption, causality, benchmark
comparability, or organizational impact. A publication or repository can
establish public association and documented content; it does not automatically
establish every contributor's personal role.

## Review and curate

Default new results to `pending`. Change a result to `accepted` or `rejected`
only when the user requests review or repository policy provides an explicit
review rule.

Keep the public-evidence ledger as external evidence. Curate accepted material
into `<instance>/knowledge/` only when the user asks or the established
repository workflow requires it, preserving the original source URL and
evidence boundary. Research ledgers and queues stay under `workspace/` and
never enter runtime retrieval.

Validate changed YAML with the repository's closest available parser or test.
Repair only the records changed by this task and report any unrelated validation
failure.

## Stop and resume

Stop only when the queue is exhausted, the user pauses or stops the task, or a
real blocker prevents further progress. Do not stop merely because one coherent
batch is complete or because results await review.

At the end, summarize completed and pruned topics, unresolved conflicts, blocked
leads, review state, and the evidence used to determine exhaustion. If stopped
early, record the remaining queue and next cluster. On the next invocation,
reconstruct state from repository files rather than assuming chat history is
available, then continue without asking for confirmation.
