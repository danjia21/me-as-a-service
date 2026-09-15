---
name: initialize-knowledge-base
description: Create or enrich a directly usable Me-as-a-Service retrieval index and its 10 résumé-informed evidence-required evaluation questions from a technical résumé, authoritative public context, and up to three optional interview answers. Use when initializing or rebuilding a person's profile. Do not use to adapt the web runtime or ingest visitor conversations.
---

# Initialize Knowledge Base

Turn a technical résumé into a live retrieval index and an instance-specific set of
10 evidence-required evaluation questions, then improve the index with public
research and optional interview answers. The first résumé-derived index must exist
before enrichment begins; there is no staging, review, approval, or publication
phase.

Read [the CLI contract](references/cli-contract.md) before changing an instance. Read
the engineering question pack at
`tools/knowledge-cli/src/maas_knowledge/question_packs/engineering.yaml` only when
selecting interview questions.

## Start or resume

Resolve the instance from an explicit path or `MAAS_INSTANCE_DIR`. Resolve the résumé
from the user's path, the already normalized input, or one unambiguous PDF or Markdown
candidate inside the instance. Ask only if no safe choice exists.

Run `status` first. If the index already has records, preserve it unless the user
explicitly requested a complete rebuild. Never clear a working index merely because
research, questioning, or another enrichment step is incomplete.

On a clean start, say once:

> I’ll build a usable index from the résumé first. I can then add authoritative public
> context and ask up to three focused questions; each useful answer will update the
> index immediately. I’ll also create 10 evidence-retrieval questions for checking the
> finished profile. Rough bullets, voice transcripts, “I don’t know,” and confidential
> omissions are all fine.

Keep later progress messages short. Do not expose schemas, internal paths, IDs, or
index mechanics. Use ordinary Markdown. Never emit `:codex-followup` markup, action
directives, simulated buttons, or prewritten response choices.

## Create the baseline index first

1. Initialize the instance and import the PDF or Markdown résumé through the CLI. The
   original and normalized text are retained as inputs.
2. Read the entire normalized résumé and replace the generic presentation defaults in
   `instance.yaml` with a curated display name, representation label, disclosure,
   welcome message, suggested questions, and any exact public profile or repository
   links supported by the input. Keep `knowledge_base.index` unchanged.
3. Turn the résumé into retrieval records covering
   identity, every role, substantial projects, publications, important skills, and
   chronology.
4. Write the complete baseline with `replace-index` only for a new empty index or an
   explicitly requested rebuild. Otherwise use `upsert-index` to preserve existing
   knowledge.
5. Create the 10-question evidence-required evaluation set described below.
6. Run `validate` before doing public research or asking interview questions. At this
   point the instance must already have a usable index.

The instance manifest contains only reusable presentation and live-index settings;
the instance directory name is its identifier:

- `display_name`, `representation_label`, and `disclosure` identify the represented
  person honestly in the interface;
- `welcome_message` is the short invitation shown beneath the welcome heading;
- `suggested_questions` contains three to five concise, varied questions that are
  answerable from the initialized corpus; and
- `links` contains only exact, deliberately curated public profile or repository URLs.

Do not restore legacy `knowledge.path`, `evaluations`, or `routing.personal_terms`
fields. The live JSON index replaces the legacy Markdown knowledge directory, the
evaluation question file has a fixed instance-relative path rather than a manifest
pointer, and runtime keyword routing is outside the current architecture.

Each record has only `id`, `subject`, `body`, and an optional `url`. Let the CLI create
the ID for a new subject. Supply the existing ID when revising a record, especially if
its subject changes.

- Keep each record focused on one coherent subject and understandable without nearby
  records.
- Put useful names, roles, projects, and technologies in the subject or body rather
  than adding tags.
- Write polished professional prose, not résumé fragments or search keywords.
- Use a URL only for an exact, deliberately curated further-reading page.
- Split broad topics into separate records instead of creating nested documents or
  oversized bodies.

Do not store source IDs, topic IDs, headings, timestamps, checksums, claims, exact
quotes, ownership values, or provenance ledgers in retrieval records.

## Create evidence-required evaluation questions

After the baseline index is usable, create
`evaluations/evidence_required.json` inside the instance. Write exactly 10 objects
using this shape:

```json
[
  {
    "id": "career_progression",
    "question": "How did you move from research into production engineering?"
  }
]
```

IDs use unique lowercase words separated by underscores. Questions must be unique,
standalone initial-turn questions that the classifier should label
`evidence_required`. Every question must ask about the represented person's
professional history, projects, research, skills, architecture, decisions, ownership,
trade-offs, or outcomes.

Derive the questions only from the normalized résumé. Read it as a description of the
person's professional areas, then write realistic interview questions typical of
those areas. Do not inspect the retrieval index, public-research records, interview
answers, or earlier evaluation questions while composing them. Avoid project names,
employer-specific implementation details, distinctive metrics, paper titles, and
phrasing copied from the résumé; the questions should require semantic retrieval and
synthesis rather than near-exact phrase matching. Address the represented person
directly as `you` and `your`, as a visitor would. Mix broad screening questions such
as "Do you have experience with microservices?" with deeper prompts about common
domain problems, technical trade-offs, evaluation methods, reliability, scaling, and
transitions between research and production. Do not make every question a detailed
scenario. The résumé must make curated evidence reasonably likely to exist, but a
question need not map to one obvious record or have a complete answer.

Do not include greetings, acknowledgements, unrelated tasks, private or sensitive
requests, or undocumented subjective opinions and hypothetical judgments that belong
to the other four conversation types. Do not store expected answers, retrieved
content, or model responses in this file.

Create the file once the baseline is written so an interrupted enrichment run still
has an evaluation set. Revise questions only when résumé changes make their premise
inaccurate, while preserving the exact count and evidence-required-only scope. Public
research, interview answers, and index changes must not influence the questions.
During an ordinary resume, preserve an existing valid question set unless the résumé
changed enough to make a question stale. An explicit rebuild replaces the complete
set from the résumé alone.

## Enrich the live index

Search for clearly matched authoritative sources using the person's name, employers,
publication titles, repositories, projects, and explicit résumé links. Prefer
publisher, university, official project, clearly matched repository, reputable
employer, award, and event pages. Skip ambiguous namesakes.

For each useful public source, write a self-contained record with its canonical URL
and apply it with `upsert-index`. Do not mirror the page or persist research rationale.
Validate after each update so an interruption always leaves the last successful index
usable.

## Ask up to three optional questions

Inspect the current index for gaps. Prefer unclear personal ownership, missing
outcomes, reusable difficult decisions or course corrections, leadership evidence,
and cross-career progression. Stop early when another answer would add little.

Ask one question at a time. Treat a reply as drafting material rather than text to
copy:

1. Rewrite it into clear, compact prose without adding facts.
2. Identify the actor for every action before choosing a pronoun. The person may have
   developed a method, the team may have used it, and the model or vehicle may have
   produced the outcome.
3. Prefer direct descriptions of what a system does and who uses it. Avoid vague
   constructions such as “the tool let me” when it enabled the team.
4. Preserve uncertainty, numbers, causality, and ownership boundaries. Remove
   confidential detail and transcription noise.
5. Upsert the polished record immediately. Never persist the raw reply.
6. Show the prose that was added and invite corrections without making confirmation a
   gate. Apply any correction as another upsert.

Skipping a question or setting a privacy boundary creates no record and does not
affect the working index.

## Finish

Run `validate`, confirm that `evaluations/evidence_required.json` contains exactly 10
unique valid question objects, and report the number of usable records and evaluation
questions. CLI validation covers the instance manifest and retrieval index; the skill
checks the evaluation file directly. There is no build, sample review,
ready-to-publish state, publication command, or separate approval step. The web
runtime is adapted to `index/records.json` separately.
