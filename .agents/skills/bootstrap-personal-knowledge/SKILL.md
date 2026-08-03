---
name: bootstrap-personal-knowledge
description: Grow a structured, evidence-grounded personal knowledge corpus from a résumé or other seed material through batch-first capture, selective guided interviewing, answer coaching, and user-approved first-person writing. Use when a user wants to expand a sparse résumé or CV into detailed project accounts, capture several missing evidence dimensions quickly, get help recalling and framing useful evidence, turn rough notes or transcripts into polished accounts, track topic coverage, or avoid duplicate interview questions.
---

# Bootstrap Personal Knowledge

Turn terse seed claims into user-approved, citable accounts without treating model
inferences or external evidence as autobiographical facts. Prefer a fast batch-first
workflow; fall back to focused guided interviewing when the evidence needs it.
Continue until the user pauses or says to stop.

## Orient the user

At the beginning of the first session, explain the process briefly and
conversationally:

- the goal is to create trustworthy, reusable accounts from sparse source material;
- the default fast path collects several related gaps in one rough response;
- rough bullets, fragments, pasted notes, transcripts, uncertain memories, and
  confidential omissions are welcome;
- the coach asks follow-ups only for material gaps or ambiguities;
- nothing enters the authoritative corpus until the user approves it;
- the user can revise, skip, switch to one-question-at-a-time guidance, pause, or
  stop at any time.

Do not repeat the full orientation later. On resume, give at most a one-sentence
reminder of the topic and unfinished stage.

## Prepare

1. Resolve the instance directory from an explicitly supplied path or
   `MAAS_INSTANCE_DIR`. Ask only when neither identifies the intended instance.
2. Read repository guidance, `<instance>/instance.yaml`, the curated résumé or
   other seed material, existing approved personal accounts, relevant public
   knowledge, drafts, and the coverage registry. Seed material may live under
   `<instance>/inputs/` or another repository-defined location such as
   `<instance>/knowledge/resume.md`.
3. Read [storage-schema.md](references/storage-schema.md) before creating or
   updating interview or coverage files.
4. Build a private coverage map across topics and these angles: context,
   ownership, constraints, decisions, alternatives, trade-offs, failures,
   collaboration, outcomes, lessons, and current reflection.
5. Reuse established evidence. Do not ask the user to restate an approved fact
   merely to fit a new answer shape.
6. Select a high-value under-covered topic. Do not ask the user to choose unless
   multiple paths would materially change the process.

Keep the trust boundaries explicit:

- seed documents and public evidence may identify topics and prefill documented
  context;
- only the user's statements and previously approved personal accounts can
  establish new autobiographical facts;
- model-generated synthesis remains a draft until the user approves it;
- directory placement is the publication boundary.

## Choose a capture mode

Use **Fast capture** by default. Use **Guided interview** when batching would
make the response confusing or when the user requests one question at a time.
Use **Deep dive** only when the user explicitly wants more depth or a topic's
importance justifies deliberate exploration.

### Fast capture

Use when a topic already has some evidence or several related coverage gaps can
be answered together. Target one intake, no more than two focused follow-ups,
and one approval cycle.

### Guided interview

Use when the topic is sparse, emotionally or confidentially sensitive, the user
is struggling to recall it, or the first batch response contains material
ambiguity. Ask one focused question at a time and coach after each answer.

### Deep dive

Use for unusually important projects or when the user wants interview practice.
Explore semantically distinct angles without requiring every generic coverage
dimension.

Switch modes based on evidence quality, not answer polish. Never make the user
repeat material already supplied during the session.

## Keep the functions explicit

Use three visibly separate labels in user-facing interview turns:

- **Interviewer:** Ask the primary intake or focused follow-up.
- **Coach:** Offer short, topic-specific memory prompts and assess whether the
  evidence is sufficient.
- **Editor:** Synthesize only supported material, then surface checks and request
  approval.

## Run fast capture

1. Summarize in one or two sentences what is already established, so the user
   knows what not to repeat.
2. Under **Interviewer**, ask one coherent primary intake question covering the
   remaining high-value gaps for one topic or project.
3. Under **Coach**, provide three to five short headings or prompts tailored to
   those gaps. These are memory aids, not hidden mandatory questions. Invite one
   batch response and explicitly allow skipped or unknown details.
4. Accept rough bullets, fragments, prose, pasted documents, or transcripts.
5. Extract a private claim ledger from the response. For each material claim,
   distinguish:
   - previously approved or documented context;
   - newly stated autobiographical evidence;
   - uncertain, inferred, or ambiguous material;
   - confidential or deliberately omitted material.
6. Assess the whole account for coherence, ownership, causality, and evidence
   quality. Ask a follow-up only when the missing answer would materially alter
   the account. Combine tightly related ambiguities into one focused follow-up;
   do not restart a serial questionnaire.
7. After two follow-ups, normally preserve remaining uncertainty as an evidence
   boundary and draft the supported account. Offer guided mode if the account is
   still too incomplete to be useful.

Do not force every coverage angle into one intake. Prefer the smallest group of
gaps that produces a coherent canonical account.

## Coach evidence

Choose only prompts that fit the topic, such as:

- situation, stakes, and the user's scope;
- scale, reliability, time, cost, data, hardware, or organizational constraints;
- architecture, actions, and important decisions;
- alternatives, trade-offs, failures, disagreements, or course corrections;
- observed outcomes, defensible measurements, lessons, and current reflection.

Give examples of the kind of useful detail, never candidate-specific facts.
Never pressure the user to estimate a metric. Qualitative impact is acceptable
when described precisely.

Prioritize clarification of:

- what the user personally did versus what the team did;
- what words such as "faster," "better," or "scaled" mean;
- the causal link between a problem, decision, and outcome;
- whether a claim is measured, observed, inferred, or uncertain;
- confidentiality and publication boundaries.

If the user cannot recall something, accept the boundary rather than repeatedly
asking for it.

## Run a guided cycle

1. Under **Interviewer**, ask exactly one focused question grounded in the seed
   or existing account.
2. Under **Coach**, give two to four tailored prompts without hiding additional
   required questions inside them.
3. After the response, acknowledge what it established and ask one focused
   follow-up only if a material gap remains.
4. Hand off to the editor when the answer is clear enough to be useful and any
   remaining uncertainty can be stated explicitly.

## Draft and approve

1. Under **Editor**, write one natural first-person canonical account for the
   topic or coherent topic slice. Prefer direct context, specific contribution,
   an important decision or trade-off, outcome, and reflection when supported.
2. Reuse approved evidence without silently changing its strength or scope.
3. Never invent metrics, dates, scale, adoption, motivations, ownership, team
   size, causality, or confidential details.
4. Add a short **Checks** section that calls out only material review items:
   strengthened wording, ambiguous ownership, unsupported quantitative claims,
   uncertainty, and confidentiality concerns.
5. Ask whether the draft is factually accurate, sounds like the user, includes
   what matters, and is safe for the knowledge base. A clear "approved," "looks
   good," or "yes" counts as approval. Revise when corrected.
6. Never write the draft to authoritative knowledge before approval.

## Save approved work

On approval:

1. Save the exact primary intake question and exact approved account as one
   source note under `<instance>/knowledge/personal/`. Prefer one canonical note
   per project or coherent topic slice rather than one note per coaching prompt.
2. Record uncertainties and deliberate omissions under `Evidence boundaries`.
3. Update `<instance>/workspace/coverage.yaml` in the same change. Mark only
   angles actually supported by the approved account; batching is not evidence
   of completeness.
4. Do not save raw scratch material unless the user explicitly requests it.
5. Validate the source with the repository loader or closest available check.
   Repair only the new note or registry entry and report unresolved failures.
6. Continue with the next high-value, semantically distinct topic unless the
   user pauses or stops.

Do not rewrite or consolidate older approved notes merely because the current
skill prefers project-level accounts. Migration is a separate user-approved
operation.

## Maintain a canonical account

Store one complete approved account rather than recruiter, technical, STAR, and
short-answer variants. Generate presentation variants later from the same
evidence to avoid contradictions.

Keep these artifacts distinct:

- the résumé identifies topics;
- approved personal notes provide autobiographical evidence;
- public research corroborates public facts but cannot establish private
  experience or personal intent;
- claim and passage indexes are derived retrieval artifacts;
- evaluation cases test behavior and are not factual authority;
- unapproved drafts, visitor conversations, and conversation summaries are not
  trusted knowledge.

Use `<instance>/knowledge/` only for approved, retrieval-eligible material.
Use `<instance>/workspace/drafts/` for explicitly saved or interrupted drafts
and `<instance>/workspace/coverage.yaml` for interview state. Do not add a
front-matter workflow or access-control field to source notes.

## Stop and resume

When the user pauses or stops:

1. Finish only an already-approved write.
2. If an editor draft exists, save it under `<instance>/workspace/drafts/` so it
   remains non-authoritative and resumable. Do not save raw scratch material
   unless requested.
3. Summarize completed topics, important gaps, the current mode, and the next
   recommended intake or question.
4. Ensure the coverage registry is sufficient to resume without repetition.

On the next invocation, reconstruct state from repository files rather than
assuming prior chat history is available.
