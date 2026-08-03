-- Run deliberately after verifying LangSmith trace export and daily_model_usage.
-- This operation is destructive. Restore legacy trace data from a database backup.
BEGIN;
DROP TABLE IF EXISTS trace_evidence;
DROP TABLE IF EXISTS turn_traces;
COMMIT;
