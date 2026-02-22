---
sidebar_position: 4
---

# Inference backend

Inference is **backend-switchable**: the video-worker invokes one of several backends per segment. This keeps the pipeline generic; the actual GPU/compute can be a managed service or your own HTTP server.

## Backends

| Backend | Description |
|--------|-------------|
| **stub** | Download segment, stub processing, upload result. Used for tests and local runs without GPU. |
| **Managed GPU endpoint** | e.g. SageMaker: async invoke with input/output URIs; worker polls for completion. Segment completion is event-driven when the endpoint writes the output (segment-output queue). |
| **HTTP** | POST to a URL you provide (e.g. your own inference server). Request/response or fire-and-forget depending on implementation. |

No cloud-specific details here; "SageMaker" is one option. Configuration (endpoint name, URL, region) is provided by your infra (e.g. Terraform outputs or env).

## Segment flow

```mermaid
sequenceDiagram
  participant VW as video-worker
  participant Storage as Object storage
  participant Backend as Inference backend
  participant Q as segment-output queue

  VW->>VW: Receive segment message, build output URI
  VW->>Backend: Invoke(input_uri, output_uri, mode)
  Backend->>Storage: Read segment
  Backend->>Storage: Write result to output URI
  Storage-->>Q: Event (object created)
  VW->>VW: Consume Q, write SegmentCompletion
```

1. Video-worker receives a segment message (from the video-worker queue).
2. Builds canonical **output URI** for the segment (defined in shared-types).
3. Invokes the backend (stub / managed endpoint / HTTP) with input and output URIs (and mode).
4. Backend reads segment from storage, runs inference, writes result to output URI.
5. When the output object is written, an event feeds the **segment-output queue**; the video-worker writes a **SegmentCompletion** record. Completion is thus **event-driven** from storage, not by polling.

## Concurrency

The **video-worker** keeps up to **INFERENCE_MAX_IN_FLIGHT** async invocations in flight: it sends multiple `InvokeEndpointAsync` calls and polls for completion.

- **SageMaker**: Infra sets **INFERENCE_MAX_IN_FLIGHT** from the endpoint **instance count** (`sagemaker_instance_count`) so the worker’s in-flight cap matches backend capacity. With one instance you get one in flight; with two instances, two. Each instance runs the inference container with gunicorn `--workers 1`, so one request at a time per instance. To get parallel inference, increase `sagemaker_instance_count` in Terraform; the video-worker will automatically use that value as its max in flight.
- **HTTP**: **INFERENCE_MAX_IN_FLIGHT** can be set via env (1–20); default is 5. Effective parallelism also depends on your server’s workers/threads.

## Package

The **stereo-inference** package provides the inference container (e.g. iw3/nunif for 2D→stereo). It is built and deployed separately (e.g. via CodeBuild and SageMaker, or run as your own HTTP service). Storage and metrics are adapter-based so the same image can target AWS or GCP.
