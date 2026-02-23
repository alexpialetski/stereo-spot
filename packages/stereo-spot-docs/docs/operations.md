---
sidebar_position: 6
---

# Cost, security, and operations

High-level levers and guardrails that apply to any cloud implementation.

## Cost

- **Main levers:** Compute (workers, inference endpoint), object storage and egress, queues, job/segment store. Segment sizing (e.g. ~50MB / ~5 min) keeps cost predictable for batch video work.
- **Guardrails:** Set **max capacity** per worker service and inference endpoint to cap scale. Use **dead-letter queues** with a max receive count; add an **alarm** when any DLQ has messages so failed messages are visible. Tag resources for billing; optionally set budget alerts.
- **Web UI:** Operator-facing links (job detail “Open logs”, top nav “Cost”) come from **OperatorLinksProvider** (see [shared-types](/docs/architecture/shared-types#operatorlinksprovider)). On AWS, when `NAME_PREFIX` is set (e.g. in ECS), aws-adapters provides the implementation (CloudWatch Logs Insights, Cost Explorer filtered by App tag). Override the cost link via `COST_EXPLORER_URL`; when `NAME_PREFIX` is unset, no operator links are shown.

## Security

- **Identity:** Use **task/worker identity** (e.g. IAM task roles) for storage and queues; no long-lived access keys in app config.
- **Network:** Run workers in private networks; expose only the web UI (e.g. via a load balancer). Use VPC endpoints for storage where available to avoid NAT and improve throughput/cost.
- **Secrets:** Store API keys or model artifacts in a secrets service; mount or pull at runtime. Do not bake secrets into images.

## Observability

- **Logs:** Emit logs with **job_id** (and **segment_index** where relevant) so one job can be traced across the pipeline. Log format is standardised: all services (web-ui, media-worker, video-worker, stereo-inference) call **`stereo_spot_shared.configure_logging()`** at startup so CloudWatch and other sinks see a consistent `%(asctime)s [%(levelname)s] %(name)s: %(message)s` with ISO timestamps.
- **Metrics:** Expose or derive metrics for segment conversion duration, queue depth, and “segments completed / total_segments” per job. Add an alarm when no new segment has completed for a job for a configured threshold to detect stuck jobs.
- **Tracing (optional):** Propagate job_id and segment_index in logs and tracing so a single job can be followed from chunking → segment processing → reassembly.

## Risks and follow-ups

- **Re-upload same job:** If the user uploads again to the same input key, the job is re-chunked and re-processed. For V1 we do not prevent or deduplicate; optional later: enforce a single upload per job or document that re-upload means re-processing.
- **Segment key and parser drift:** The segment key format and parser live only in **shared-types**; all workers use that library. Add integration tests that round-trip key generation and parsing to keep both sides in sync.

## See also

- [Runbooks (generic)](/docs/runbooks) — DLQ handling, scaling, reassembly trigger.
- [AWS runbooks](/docs/aws/runbooks) — AWS-specific procedures and commands.
