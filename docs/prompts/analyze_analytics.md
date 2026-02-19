# Analyze analytics (LLM prompt)

**Context:** Stereo-spot converts 2D video to stereo (anaglyph/SBS). Pipeline: upload → chunking → video-worker invokes SageMaker per segment → segment-output → reassembly. Metrics: segment conversion duration (per segment; per MB useful for ETA).

**Inputs:**

1. **History table:** `packages/analytics/analytics_history.md` — table of past runs (cloud, backend, instance type, avg_duration_sec, eta_seconds_per_mb, date, notes).
2. **Latest analytics:** Output of the gather target, e.g. `docs/analytics/latest.json` (or paste the JSON here).

**Task:**

- Compare the latest run with the history table.
- Suggest infra changes (instance type, segment size, `eta_seconds_per_mb`) and whether the last change was worth it.
- Suggest adding a new row to `packages/analytics/analytics_history.md` with the new numbers.

**Output (concise):**

1. Short summary of how the latest run compares to history.
2. Suggested Terraform variable changes (if any): e.g. `eta_seconds_per_mb`, `sagemaker_instance_type`, etc.
3. The new row to append to the history table (same columns: Cloud | Backend | InstanceType | avg_duration_sec | eta_seconds_per_mb | date | notes).

User will paste this prompt plus the latest analytics JSON and current history table into Cursor/LLM when they run the gather target after a change.
