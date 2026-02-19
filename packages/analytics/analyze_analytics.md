# Analyze analytics (LLM prompt)

**Context:** Stereo-spot converts 2D video to stereo (anaglyph/SBS). Pipeline: upload → chunking → video-worker invokes SageMaker per segment → segment-output → reassembly. Metrics: segment conversion duration (per segment) and conversion seconds per MB (for ETA).

**Inputs:**

1. **History table:** `packages/analytics/analytics_history.md` — table of past runs (cloud, backend, instance type, avg_duration_sec, eta_seconds_per_mb, date, notes).
2. **Latest analytics:** Output of the gather target, e.g. `packages/analytics/latest.json` (or paste the JSON here).

**Structure of latest.json:**

- Top-level: `timestamp`, `cloud`, `endpoint_name`, `region`, `period_hours`, `metrics`, `log_summary`.
- Under `metrics`:
  - **ConversionSecondsPerMb** (when present): preferred source for **eta_seconds_per_mb**. Shape: `{ "overall_avg": <number> }` — use `overall_avg` as eta_seconds_per_mb. If only **ConversionSecondsPerMb_by_bucket** exists (per-bucket keys like "0-5", "5-20", "20-50", "50+" MB), use the weighted average across buckets or the "20-50" bucket for typical ~50MB segments.
  - **SegmentConversionDurationSeconds**: legacy key (Cloud only) — `Datapoints` with `Average` gives avg_duration_sec. Use for **avg_duration_sec** when no by_bucket data.
  - **SegmentConversionDurationSeconds_by_bucket** (when present): per-bucket duration (keys "0-5", "5-20", "20-50", "50+"). Use for avg_duration_sec (e.g. weighted average or dominant bucket) and to interpret segment-size mix.
  - **Legacy:** If only `SegmentConversionDurationSeconds` (no bucket, no ConversionSecondsPerMb) exists, compute eta as `avg_duration_sec / segment_size_mb` with segment size ~50MB.

**Task:**

- Compare the latest run with the history table.
- **eta_seconds_per_mb:** Prefer **ConversionSecondsPerMb**.overall_avg when present; otherwise use ConversionSecondsPerMb_by_bucket (weighted or "20-50"); otherwise fall back to `avg_duration_sec / segment_size_mb` (~50MB).
- When **ConversionSecondsPerMb_by_bucket** or **SegmentConversionDurationSeconds_by_bucket** exists, note the segment-size mix (e.g. "mostly 0-5 MB") so the user understands if ETA is dominated by small segments.
- Suggest infra changes (instance type, segment size, `eta_seconds_per_mb_by_instance_type`) and whether the last change was worth it.
- Suggest adding a new row to `packages/analytics/analytics_history.md` with the new numbers.

**Output (concise):**

1. Short summary of how the latest run compares to history.
2. Suggested Terraform variable changes (if any): e.g. `eta_seconds_per_mb_by_instance_type` (map in `packages/aws-infra/variables.tf`), `sagemaker_instance_type`, etc.
3. The new row to append to the history table (same columns: Cloud | Backend | InstanceType | avg_duration_sec | eta_seconds_per_mb | date | notes). Use the preferred eta source above for eta_seconds_per_mb.

User will paste this prompt plus the latest analytics JSON and current history table into Cursor/LLM when they run the gather target after a change.
