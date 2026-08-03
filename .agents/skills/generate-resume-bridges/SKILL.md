---
name: generate-resume-bridges
description: Generate compact, retrieval-ready Markdown bridge documents from a résumé when common interview questions require facts scattered across several résumé passages or an approved public professional contact link is buried in a broader résumé passage. Use when an answerable question about career chronology, employers, roles, projects, skills, leadership, education, research, recognition, public professional contact, or factual cross-role comparisons retrieves only part of the answer; when a one-passage retrieval limit needs a trustworthy aggregate or targeted passage; or when an instance needs résumé-derived summaries without adding new autobiographical claims.
---

# Generate Resume Bridges

Create a small set of résumé-scoped aggregate or targeted passages that answer
common questions without changing runtime retrieval. Treat each bridge as a
derived retrieval aid, not as a new source of personal evidence.

Read [bridge patterns](references/bridge-patterns.md) completely before choosing
question families or drafting documents.

## Prepare

1. Resolve the instance from an explicit path or `MAAS_INSTANCE_DIR`. Ask only
   when neither identifies the intended instance.
2. Read repository guidance, `<instance>/instance.yaml`, every root-level
   résumé or profile document under `<instance>/knowledge/`, the ingestion
   implementation, existing root-level bridge documents, and the instance or
   repository disclosure policy when one exists.
3. Inspect the optional evaluation fixture and recent failing questions when
   available. Use visitor transcripts only to discover question shapes, never
   as factual evidence.
4. Determine how the loader splits the résumé into passages. Identify useful
   questions whose answers span multiple passages and lack one existing passage
   that contains the complete answer. Also identify an explicitly approved
   public professional contact link that exists in a résumé passage but cannot
   win the current résumé candidate limit for direct contact questions.

## Select bridge documents

Choose only high-value question families supported by the résumé. Prefer three
to eight bridges for a substantial résumé and fewer for a sparse one. Do not
create a bridge merely to paraphrase one already sufficient passage, except for
an approved public professional contact link that needs a targeted passage to
win the current retrieval limit.

Prioritize:

- questions already observed to retrieve incomplete evidence;
- natural interview questions spanning multiple roles or sections;
- facts likely to remain useful together in one answer;
- compact summaries that can stand alone as one retrieval passage.
- direct contact questions when an approved LinkedIn or professional profile
  link is otherwise buried in a broader résumé passage.

Do not create bridges for undocumented opinions, motivations, preferences,
feelings, causal explanations, or subjective rankings. A factual comparison
may co-locate explicit facts from several roles, but it must not decide which
role, project, or result was better, harder, more important, or preferred.

Treat contact information as sensitive. Create a public-contact passage only
when the exact channel and URL appear in the résumé and the user or disclosure
policy explicitly approves that channel for publication. Never infer a URL.
Do not include a private email address, phone number, home address, or messaging
preference merely because it appears in source material.

## Draft each bridge

Create each bridge as one Markdown file directly under
`<instance>/knowledge/`, so the current loader assigns it to résumé scope. Use
only scalar `id` and `title` front matter accepted by the loader. Give the body
one top-level heading and one compact passage.

```markdown
---
id: resume-bridge-career-history
title: Career history from the résumé
---

# Career history and previous roles

The complete résumé-derived summary goes here as one coherent passage.
```

Use stable filenames such as `resume-bridge-career-history.md`. Use
`resume-public-contact.md` for the approved professional contact passage, with
a `resume-public-contact` id and a `Public professional contact` heading.
Include the ordinary words a visitor is likely to use, such as "worked before",
"previous roles", "education", "technologies", "contact", or "reach out",
when they fit naturally and remain factually accurate. Do not add keyword
lists, hidden query text, or repetitive search-engine prose.

Write for evidence retrieval, not as a polished chatbot answer:

- preserve names, roles, dates, measurements, ownership strength, and scope;
- combine only claims explicitly present in the résumé;
- use neutral factual wording that generation can safely convert to first
  person;
- distinguish employment, internships, education, research, and projects;
- preserve uncertainty and avoid strengthening team contributions into sole
  ownership;
- omit details that do not help the target question family.

## Verify before writing

Build a private claim map for every proposed sentence. Point each material
clause to the exact résumé entry that supports it. Remove any clause that
depends on inference, general knowledge, another generated bridge, model
output, or a visitor message.

Check for contradictions with existing curated knowledge. If the résumé and
another authoritative document disagree, report the conflict and do not choose
silently. Derive bridges from the résumé unless the user explicitly expands
the allowed source set.

Present the proposed bridge set and material claim mappings for review when a
bridge requires nontrivial synthesis. Straight aggregation of explicit résumé
facts may be written directly when the user already asked for generation.

## Validate

1. Load the new files with the repository's production ingestion path.
2. Confirm that every bridge becomes exactly one résumé-scoped passage.
3. Run focused retrieval queries representing each target question family.
   Confirm that the intended bridge is the top résumé result under the current
   candidate limit. For public contact, include direct forms such as "How can I
   reach you?" and "Where can I contact you?" and confirm that the exact
   approved URL is present in the returned passage.
4. Add or update evaluation cases for the observed question shapes when an
   evaluation fixture exists. Expected facts must match the bridge and résumé.
5. Run the relevant ingestion, retrieval, instance, and evaluation tests.
6. Report generated bridges, skipped families, source conflicts, and retrieval
   queries that still fail.

Do not modify retrieval limits, routing schemas, or application code as part of
this skill unless the user separately requests an architecture change.
