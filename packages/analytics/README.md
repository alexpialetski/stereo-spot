# stereo-spot-analytics

Gather conversion metrics for StereoSpot from AWS CloudWatch (and later GCP Cloud Monitoring).

## Usage

From the repo root, run via Nx with a configuration so `--env-file` is set per cloud:

```bash
# AWS (default): uses packages/aws-infra/.env
nx run analytics:gather

# Explicit AWS
nx run analytics:gather --configuration=aws

# GCP (when implemented): uses packages/gcp-infra/.env
nx run analytics:gather --configuration=gcp
```

Or run the CLI directly (e.g. after `pip install -e packages/analytics`):

```bash
python -m stereo_spot_analytics gather --env-file packages/aws-infra/.env [--output path] [--period-hours 24]
```

The script loads env from `--env-file`, reads `METRICS_ADAPTER` (aws | gcp), and calls the corresponding adapter’s `get_conversion_metrics`. Output is written to `docs/analytics/latest.json` by default.

**History table:** Maintain `packages/analytics/analytics_history.md` (past runs by cloud, backend, instance type, etc.). Use **docs/prompts/analyze_analytics.md** with an LLM to compare latest output with history and suggest infra changes.

## Dependencies

- **shared-types**: `AnalyticsSnapshot` model and `ConversionMetricsProvider` protocol
- **aws-adapters**: `get_conversion_metrics()` (CloudWatch)
- **gcp-adapters** (future): same interface for GCP
