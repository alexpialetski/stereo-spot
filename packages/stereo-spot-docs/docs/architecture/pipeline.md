---
sidebar_position: 2
---

# Pipeline concepts

End-to-end flow: **upload → chunking → segment processing (inference) → segment completion → reassembly trigger → reassembly → final output**. Storage and queues are described in abstract terms (job store, queues, object storage) so the flow applies to any cloud.

## High-level flow

```mermaid
flowchart LR
  A[Upload] --> B[Chunking]
  B --> C[Segment processing]
  C --> D[Segment completion]
  D --> E[Reassembly trigger]
  E --> F[Reassembly]
  F --> G[Final output]
```

1. **Upload** — User gets a presigned URL and uploads the source file. An event (e.g. object-created) notifies the **chunking queue**.
2. **Chunking** — A worker consumes the chunking message, splits the source with ffmpeg into segments, and uploads segment files to object storage. Segment keys follow a **canonical format** (defined in shared-types). When done, the worker updates the job: **total_segments** and **status = chunking_complete** in a single atomic update.
3. **Segment processing** — Object-created events for segment files feed a **video-worker queue**. Workers invoke the **inference backend** (stub, managed GPU endpoint, or HTTP) per segment. Inference reads the segment and writes the result to the output bucket.
4. **Segment completion** — When the inference side writes a segment output, an event feeds a **segment-output queue**. A worker writes a **SegmentCompletion** record to the segment-completion store (one record per segment, ordered by segment_index).
5. **Reassembly trigger** — After each SegmentCompletion put, the video-worker runs **trigger-on-write**: if the job has **status = chunking_complete** and **count(SegmentCompletions) == total_segments**, it conditionally creates a reassembly lock and sends **job_id** to the **reassembly queue**.
6. **Reassembly** — A worker consumes the reassembly queue, builds the concat list from the segment-completion store (no object list), runs ffmpeg concat, uploads **final.mp4**, and updates the job to **status = completed**.

## Job status lifecycle

```mermaid
stateDiagram-v2
  [*] --> created
  created --> chunking_in_progress: optional
  created --> chunking_complete: chunking done
  chunking_in_progress --> chunking_complete: total_segments + status updated
  chunking_complete --> completed: reassembly done, final.mp4 written
  completed --> [*]
```

- **created** — Set when the job is created (e.g. by web-ui).
- **chunking_in_progress** — Set when chunking starts (optional; helps recovery tools find stuck jobs).
- **chunking_complete** — Set in one atomic update when chunking finishes (**total_segments** and **status**).
- **completed** — Set by the reassembly worker after writing the final file.

Only the job store is authoritative for status.

## Segment key convention

Segment object keys follow **one** format so chunking and segment-processing workers stay in sync. The **parser lives only in shared-types**; both media-worker (when building keys) and video-worker (when parsing events) use it. Example pattern:

`segments/{job_id}/{segment_index:05d}_{total_segments:05d}_{mode}.mp4`

Zero-padding keeps lexicographic order and avoids ambiguity.

## Idempotency

- Chunking and segment processing use **deterministic keys**; retries overwrite the same objects.
- Reassembly trigger uses a **conditional create** on a lock table so at most one reassembly message per job is sent.
- Reassembly worker uses a **conditional update** on the lock so only one worker runs reassembly per job.
