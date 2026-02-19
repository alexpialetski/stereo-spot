# Analytics history (conversion duration, ETA coefficient)

When you change infra (instance type, segment length, or ETA coefficient), run the analytics gather target, update this table with the new row, then use the LLM prompt to compare and propose further changes.

| Cloud | Backend   | InstanceType   | avg_duration_sec | eta_seconds_per_mb | date       | notes                |
| ----- | --------- | -------------- | ---------------- | ------------------ | ---------- | -------------------- |
| aws   | sagemaker | ml.g4dn.xlarge | —                | 5.0                | 2026-02-18 | baseline placeholder |
