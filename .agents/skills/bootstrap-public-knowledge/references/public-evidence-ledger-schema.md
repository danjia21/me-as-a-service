# Public-evidence ledger schema

Adapt paths to repository conventions, but keep external research separate from
approved autobiographical sources.

Store one YAML document per coherent topic cluster:

`<instance>/workspace/research/<topic-id>.yaml`

Recommended shape:

```yaml
version: 1
topic_id: example-detector
related_source_ids:
  - resume
queries:
  - Example detector conference paper
results:
  - id: example-detector-paper
    url: https://example.org/canonical-source
    title: Example detector
    publisher: Example publisher
    retrieved_at: 2026-07-23
    source_kind: paper
    authority: primary
    related_entities:
      - Example detector
    direct_support:
      - The paper describes a 2D LiDAR person detector.
    inference_notes: []
    limitations:
      - Verify benchmark details against the final proceedings version.
    review_status: pending
    license_notes: Store metadata and a summary; do not copy the full text.
```

Use `primary` or `secondary` for authority and `pending`, `accepted`, or
`rejected` for review status. Record direct support as paraphrased atomic claims.
Put interpretation in `inference_notes`; never mix it into `direct_support`.

Deduplicate tracking URLs and mirrors in favor of canonical pages. If two
credible sources conflict, retain both entries and describe the conflict in
their limitations.

## Queue

Store the resumable cluster inventory at:

`<instance>/workspace/research/queue.yaml`

Recommended shape:

```yaml
version: 1
updated_at: 2026-07-25
clusters:
  - id: example-detector
    title: Example detector
    status: completed
    leads:
      - IROS 2020 paper
      - official implementation
      - NVIDIA Jetson award
    discovered_from:
      - resume
    notes: []
```

Use `pending`, `in_progress`, `completed`, `pruned`, or `blocked` for cluster
status. Keep cluster IDs stable. When discovery adds a cluster, append it and
record the source cluster or artifact in `discovered_from`. Record the reason
for every pruned or blocked cluster in `notes`.
