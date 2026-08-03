# Resume bridge patterns

Use these patterns to identify question families, not as a checklist that must
produce one file per heading. Generate only bridges that the résumé supports
and the current passage layout cannot answer reliably with one result.

## Career chronology

Questions:

- Where else have you worked?
- What did you do before your current role?
- Walk me through your career.
- Which roles came before or after a named employer?

Bridge content: employers, role titles, dates, and transitions that are explicit
in the résumé. Keep employment, internships, research appointments, and study
distinct.

## Project and system inventory

Questions:

- What kinds of systems have you built?
- Which projects involved production machine learning?
- What work have you done across robotics and autonomous driving?

Bridge content: a compact inventory grouped by role or domain. Preserve whether
the person designed, implemented, co-developed, contributed to, or evaluated
each system.

## Skills across roles

Questions:

- Where have you used Kubernetes, Python, or a named technology?
- How has your machine-learning work changed across roles?
- Which roles combined research and production engineering?

Bridge content: only explicitly named technologies or methods, attached to the
roles or projects where the résumé places them. Do not infer a skill from a job
title or adjacent domain knowledge.

## Leadership and ownership

Questions:

- Where have you led architecture work?
- What evidence shows technical leadership?
- Which projects did you own versus contribute to?

Bridge content: explicit ownership language such as principal architect,
primary implementer, supervisor, or contributor. Preserve qualifiers and team
boundaries. Do not convert technical ownership into people management.

## Education and research chronology

Questions:

- What is your academic background?
- How did your education connect to your research?
- Where did you study and what did you work on?

Bridge content: institutions, degrees, dates, theses, and documented research
topics. Keep education separate from employment unless the résumé explicitly
links them.

## Publications, outcomes, and recognition

Questions:

- What are your main research contributions?
- Which projects produced publications, awards, or deployed results?
- What measurable outcomes appear across your résumé?

Bridge content: publication counts, named papers, awards, benchmarks,
deployments, adoption, or other outcomes exactly as stated. Preserve attribution
and whether results were individual, team-level, measured, or externally
recognized.

## Factual role comparisons

Questions:

- How did your work at two employers differ?
- Which roles focused on research and which on production systems?
- How do two named projects differ technically?

Bridge content: parallel explicit facts for both sides, organized around the
dimensions asked about. Do not infer preference, difficulty, importance,
motivation, or causality. If the résumé does not support both sides, skip the
bridge or narrow it to a supported inventory question.

## Public professional contact

Questions:

- How can I reach you?
- Where can I contact you?
- Do you have a LinkedIn profile?

Use this targeted passage only when the résumé already contains the exact
professional profile label and URL, the channel is explicitly approved for
publication, and its existing passage does not win the current résumé candidate
limit. Use `resume-public-contact.md` with one `Public professional contact`
passage. Preserve the exact label and URL. Do not add messaging preferences or
invite contact through any undocumented channel.

Do not copy private email addresses, phone numbers, home addresses, or other
personal contact details into a bridge merely because they appear in source
material. Require explicit user or disclosure-policy approval for the specific
channel.

## Usually skip

Do not generate a bridge for:

- one project already contained in one coherent passage;
- personal preferences, feelings, motivations, memories, or undocumented
  decisions;
- speculative career narratives such as why the person changed fields;
- generic interview coaching or claims about role fit;
- exhaustive duplication of the entire résumé;
- facts available only from visitor messages or generated answers.
- contact details or messaging preferences that lack explicit publication
  approval.
