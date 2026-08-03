# Evaluation fixture schema

Create `<instance>/evaluations/questions.yaml` as a YAML list. Every case must
contain all fields below. Read curated evidence only from
`<instance>/knowledge/`; never derive cases from `inputs/` or `workspace/`.

| Field                 | Type                                    | Meaning                                                               |
| --------------------- | --------------------------------------- | --------------------------------------------------------------------- |
| `id`                  | string                                  | Stable, unique, lowercase kebab-case identifier                       |
| `question`            | string                                  | Visitor's current message                                             |
| `question_type`       | string                                  | Stable analysis label such as `direct_fact` or `contextual_follow_up` |
| `answerability`       | `answerable` or `insufficient_evidence` | Whether curated evidence can support the requested personal claim     |
| `expected_route`      | route string                            | Final application route expected after routing and evidence checks    |
| `must_cite`           | boolean                                 | Whether a correct response must include personal-evidence citations   |
| `prior_user_messages` | string list                             | Earlier visitor turns required to interpret this case                 |
| `expected_sources`    | string list                             | Source IDs expected or deliberately checked for support               |
| `required_facts`      | string list                             | Source-grounded facts or behavioral requirements                      |
| `relevant_sections`   | string list                             | Exact source section paths retrieval should find                      |

Allowed routes:

- `conversational`: in-scope social or clarifying turn; no citation.
- `grounded`: personal question supported by curated evidence; citation
  required.
- `insufficient_evidence`: relevant personal question or premise that the
  corpus cannot support; no citation.
- `redirected`: substantive request outside the represented person's interview
  scope; no citation.

Use exact source IDs and section paths emitted by ingestion. For contextual
cases, keep `question` natural and put only the minimum antecedent in
`prior_user_messages`. For unsupported premises, leave `relevant_sections`
empty; `expected_sources` may identify a source checked for absence. For
redirected and social cases, both source lists should normally be empty.

Example:

```yaml
- id: project-direct-fact
  question: What did Alex build for the search platform?
  question_type: direct_fact
  answerability: answerable
  expected_route: grounded
  must_cite: true
  prior_user_messages: []
  expected_sources:
    - resume
  required_facts:
    - Alex built the documented indexing pipeline.
  relevant_sections:
    - Experience > Example Company

- id: project-follow-up
  question: What happened next?
  question_type: contextual_follow_up
  answerability: answerable
  expected_route: grounded
  must_cite: true
  prior_user_messages:
    - What did Alex build for the search platform?
  expected_sources:
    - resume
  required_facts:
    - The prior turn establishes the search platform as the antecedent.
  relevant_sections:
    - Experience > Example Company

- id: unsupported-team-size
  question: How did Alex manage a team of 50 engineers?
  question_type: unsupported_premise
  answerability: insufficient_evidence
  expected_route: insufficient_evidence
  must_cite: false
  prior_user_messages: []
  expected_sources: []
  required_facts: []
  relevant_sections: []

- id: unrelated-code-request
  question: Build a production service for my startup.
  question_type: unrelated_expert
  answerability: insufficient_evidence
  expected_route: redirected
  must_cite: false
  prior_user_messages: []
  expected_sources: []
  required_facts:
    - The request should be redirected rather than answered.
  relevant_sections: []
```

Before finishing, verify:

- IDs are unique and stable.
- Every required personal fact is stated or directly entailed by a curated
  source.
- Every `relevant_sections` value exists exactly as written.
- Every grounded case cites; every other route does not.
- Cases test the desired behavior rather than mirror the current router.
- Exact model-written answers are absent.
