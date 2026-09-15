# Knowledge index CLI contract

Run commands from `tools/knowledge-cli` after `uv sync --all-groups`:

```text
uv run maas knowledge <command> --instance /absolute/instance/path [input]
```

Every command writes one compact JSON object to stdout. Exit code `0` returns
`{"ok": true, "result": ...}`. Exit code `2` returns
`{"ok": false, "error": "file and field context"}`.

## Commands

```text
init
status
import-resume <resume.pdf|resume.md>
replace-index <records.yaml|json>
upsert-index <records.yaml|json>
remove-records <record-id> [record-id ...]
validate
```

All commands require an explicit `--instance` path. Writes use atomic file
replacement, so a failed update does not damage the existing index.

## Files

```text
instance/
|-- instance.yaml
|-- evaluations/
|   `-- evidence_required.json
|-- inputs/
|   `-- resume/
|       |-- original
|       |-- normalized.md
|       `-- metadata.json
`-- index/
    `-- records.json
```

`index/records.json` is the live retrieval collection and the only knowledge file the
web runtime needs. It is a JSON array. The initialization skill separately writes 10
résumé-informed questions to `evaluations/evidence_required.json` for the live
evaluation script; the knowledge CLI does not create, load, or validate that file.
There are no source copies, generated documents, workflow ledgers, build directories,
manifests, or publication state.

`init` creates an `instance.yaml` with safe generic presentation defaults, the live
index path, a welcome message, starter suggested questions, and an empty links object.
The instance directory name is its identifier. On an older minimal manifest,
initialization removes obsolete `schema_version` and `id` fields and backfills missing
fields without replacing existing values. After résumé import, the initialization
skill curates the generic fields from the represented person's source material. The
manifest contract is:

```yaml
display_name: Casey Morgan
representation_label: Evidence-backed interview agent
disclosure: This is an AI representation of Casey Morgan, not the person themself.
welcome_message: Ask me about my work, background, or how I approach professional decisions.
knowledge_base:
  index: index/records.json
suggested_questions:
  - Tell me about your professional background.
  - What project best represents your work?
  - What did you learn from a difficult engineering decision?
links: {}
```

The new manifest does not use the legacy `knowledge.path`, `evaluations`, or
`routing.personal_terms` fields. Evaluation questions use their fixed path and do not
need a manifest pointer.

Importing or replacing a résumé never clears an existing index. The caller must write
the new résumé-derived records after interpreting the normalized text.

## Record updates

`replace-index` and `upsert-index` accept:

```yaml
schema_version: 1
records:
  - subject: Sensor dataset curation at Acme Robotics
    body: >-
      At Acme Robotics, I developed ... The resulting workflow enabled the team ...
  - id: record-existing1
    subject: Pedestrian-detection publication
    body: The publication introduces ...
    url: https://example.org/publication
```

Each persisted element contains exactly:

```json
{
  "id": "record-0123456789abcdef",
  "subject": "Sensor dataset curation at Acme Robotics",
  "body": "...",
  "url": "https://example.org/further-reading"
}
```

`url` is omitted when there is no public further-reading page. The CLI generates a
stable ID from a new record's subject when `id` is omitted. To revise an existing
record, provide its ID; otherwise a changed subject creates a new record.

The complete index must have unique IDs, case-insensitively unique subjects, and
unique normalized URLs. Tracking parameters and fragments are removed from URLs.

- `replace-index` atomically replaces the complete array. Use it for an empty index or
  an explicitly requested full rebuild.
- `upsert-index` atomically adds new records and replaces matching IDs. Use it for
  public context, interview answers, and corrections.
- `remove-records` atomically removes exact IDs and rejects unknown IDs.
- `validate` checks the instance manifest, persisted four-field record contract, and
  uniqueness constraints.

Raw interview replies, research rationale, source IDs, topic maps, coverage ledgers,
claims, exact quotations, ownership scores, sample answers, and visitor messages must
not be persisted.
