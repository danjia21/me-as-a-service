# Public knowledge document schema

Adapt paths to repository conventions, but keep curated public knowledge
separate from the research ledgers it is derived from.

## One file per question

Create one file per focused question a visitor could plausibly ask:

`<instance>/knowledge/public/<topic-id>-<question-slug>.md`

A single research topic commonly yields several files (for example, what a
project is, what results it publicly reports, where it was published, and
how it was deployed), and a single source URL commonly informs more than one
of those files. Do not force one file per source and do not force one file
per topic; split on the question, using whatever accepted sources actually
answer it.

Use only metadata accepted by the repository's source loader. The current
Me-as-a-Service loader accepts scalar front matter with these fields, exactly
as in `knowledge/personal/`:

```markdown
---
id: dr-spaam-what-it-is
title: What DR-SPAAM is and how it works
---

DR-SPAAM is a person detector for sequences of 2D LiDAR scans, presented at
IROS 2020. Instead of
explicitly aligning prior scans, it recurrently updates a feature template
and applies spatial attention across the scan sequence. The authors report
70.3 percent average precision on the DROW benchmark's 0.5 m association
threshold, versus 67.9 percent for their retrained five-scan DROW baseline,
and note the model does not use odometry information.

## Further reading

- DR-SPAAM paper (arXiv): https://arxiv.org/abs/2004.14079
```

Do not use an `# Approved account` heading anywhere in a public document: the
runtime loader treats that heading as the marker for a first-person personal
account and requires the personal-note shape. Public documents are
third-person, evidence-grounded answers, not autobiographical accounts, and
must stay structurally distinct so they are never mistaken for one. For the
same reason, do not use an `## Experience` heading.

Do not add front-matter fields beyond `id` and `title`; the loader rejects
unknown fields.

## Write from the source, not from the ledger claims verbatim

Fetch and read each source URL the file draws on before writing it, even
though the research ledger already recorded `direct_support` claims for it.
The ledger is a verified index of what a source supports, not a substitute
for reading it: use it to confirm the source is worth reading again and to
know what to look for, then go back to the source to pull the specific detail
that answers this file's question.

Rewrite in your own words. Do not paste paragraphs, transcribe figures, or
reproduce code from the source; paraphrase the relevant facts and respect
each ledger result's `license_notes`. A short verbatim phrase is acceptable
only when it is brief, clearly load-bearing (a term of art, a named result),
and not the bulk of the passage.

When a source is long, extract only the portion relevant to this file's
question. Do not summarize the entire document into one file; a single long
paper can and should be split across multiple question-focused files, each
pulling only its relevant portion.

If a source is no longer reachable when drafting, fall back to the ledger's
recorded `direct_support` claims, and say so in the change you report to the
user rather than silently treating the ledger text as freshly verified.

## Further reading section

Give a file a `## Further reading` heading, as its own top-level section,
listing only the source(s) actually used to write that file. The runtime
loader parses this heading specially: it is stripped out of the retrievable
passage text and stored as structured, labeled links the assistant may offer
a visitor ("you can read more here") — it is not shown to the model as
ordinary evidence prose, and it must not be mixed into the answer text
itself.

Format every entry as exactly one item per line:

```markdown
## Further reading

- Label: https://canonical-url
```

- The label should name the source clearly (for example `DR-SPAAM paper
(arXiv)` or `RWTH project page`), not just repeat the URL.
- Use the canonical URL from the ledger result, deduplicating tracking
  parameters or mirrors.
- Keep the list short — only sources this specific file draws on, not every
  source in the topic's ledger.
- The section must not be empty; omit it entirely for a file that, unusually,
  draws on no single citable URL (this should be rare for public knowledge).
- Do not add a `Source:` line or inline URL anywhere else in the body; the
  loader sends passage text to the model verbatim, and a URL embedded in
  prose is inert noise there, not a usable citation.

## Evidence boundary

Public documents may state what a public source directly says or what
multiple public sources jointly corroborate. They must not assert the
person's private motivation, individual responsibility, decision process, or
confidential work — that material belongs in `knowledge/personal/` and can
only be written and approved through the personal-knowledge interview
process. When a public source only supports a claim about the group or
project as a whole, write it that way rather than attributing it to the
person individually. Fold in a genuine limitation (a discrepancy, an
unreproduced benchmark, a stale claim) as a plain sentence in the prose
rather than a separate labeled block; keep the file readable as one coherent
answer.

## Ledger review state

Only convert a ledger result into a public document after the user has
reviewed it. Update the result's `review_status` in
`<instance>/workspace/research/<topic-id>.yaml` to `accepted` or `rejected`
to record the decision, and change nothing else in the ledger. Leave
`pending` results out of every curated document until they are reviewed.

## Id collisions

Check that a chosen `id` does not collide with any existing source id
anywhere under `<instance>/knowledge/` before writing; source ids must be
unique across the whole corpus, not just within `public/`. Disambiguate on
collision instead of overwriting an unrelated document.
