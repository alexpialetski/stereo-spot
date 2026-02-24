---
sidebar_position: 5
---

# Runbooks (generic)

Cloud-agnostic procedures. For AWS-specific commands and URLs, see [AWS runbooks](/docs/aws/runbooks).

## DLQ handling

Each main queue has a **dead-letter queue (DLQ)**. After a configured number of failed receives, messages move to the DLQ.

- **Inspect:** Receive messages from the DLQ (without deleting) to see body and attributes.
- **Replay:** Send the same body to the main queue, then delete the message from the DLQ. Fix the underlying cause before replaying.
- **Discard:** Purge the DLQ when messages are known bad or no longer needed (use your cloud's purge API with care).

## Scaling and visibility timeout

- **Max capacity:** Configure max tasks per worker (e.g. in Terraform or your infra) to cap scale.
- **Visibility timeout:** Set per queue; should be at least as long as the maximum time a single message might be processed. If workers regularly exceed it, increase the value so messages are not redelivered mid-processing.
- **Long polling:** Workers should use long polling (e.g. wait up to 20s for a message) so new messages are picked up quickly.
- **0/0 tasks:** If workers scale from zero on queue depth, 0 running tasks is normal when queues are empty. Add work to grow the queue; scaling will add tasks. To force one task (e.g. for testing), set desired count to 1 via your cloud's API; auto scaling may change it again.

## Job stuck at chunking_complete

When a job shows **status = chunking_complete** but never moves to **completed**, the pipeline after chunking is failing. Flow: segments → segment queue → segment worker (writes completions) → **reassembly trigger** (after each completion put; video-worker sets **reassembling**) → reassembly queue → media-worker (writes final.mp4 or .reassembly-done) → output-events → video-worker sets **completed**.

1. **Check queues:** Are messages stuck in the segment queue, or in the reassembly queue? Check worker logs for the relevant service.
2. **Check completions:** Count segment-completion records for the job; it should equal **total_segments**. If so, the trigger logic should have sent to the reassembly queue when the last completion was written.
3. **Check trigger/lock:** Ensure the reassembly-triggered lock exists for the job if the trigger ran. If the trigger never ran (e.g. bug or crash), you may need to **manually send the reassembly message** and create the lock so only one reassembly runs. Use your cloud's job store and queue APIs; see AWS runbooks for exact commands.

## Reassembly trigger (logic)

The reassembly trigger runs **after each SegmentCompletion put**. It only sends to the reassembly queue when:

- Job **status = chunking_complete**
- **count(SegmentCompletions for job_id) == total_segments**

It uses a **conditional create** on a lock row (e.g. ReassemblyTriggered) so at most one reassembly message per job is sent even when multiple completions land concurrently. No separate stream or function is required for this path.
