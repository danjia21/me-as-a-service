---
id: lantern-incident-workflow
title: Lantern incident investigation workflow
---

# Interview question

How did the Lantern replay system change incident investigation?

# Approved account

Before Lantern, an engineer assembled logs from several vessel services by hand and reconciled their timestamps during an incident review. I designed a shared event envelope and a replay worker that reconstructed the sequence deterministically. The first useful outcome was consistency: two engineers investigating the same data now started from the same ordered timeline. We did not record a defensible percentage reduction in investigation time.

# Evidence boundaries

- The example intentionally contains no real employer, project, or person.
- No quantitative time-saving claim was recorded.
