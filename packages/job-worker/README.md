# job-worker

Consumes the **job-status-events** SQS queue (duplicate S3 events from the output bucket). Writes SegmentCompletions, updates job status (failed/completed/reassembling), and triggers reassembly when all segments are complete. Single place for job progress and lifecycle used by the UI.

See [packages/stereo-spot-docs](packages/stereo-spot-docs) for architecture and pipeline.
