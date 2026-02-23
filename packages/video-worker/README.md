# Video worker

Consumes video-worker and output-events queues; invokes inference (SageMaker/HTTP/stub) and triggers reassembly when segments complete. With SageMaker: invokes async, deletes the segment message immediately, and records the invocation in a store; SegmentCompletion is written only when the output-events consumer processes a SageMaker result event (no polling).

**Main targets:** `test`, `lint`, `build`, `deploy`.

**Full documentation:** [Packages → video-worker](https://alexpialetski.github.io/stereo-spot/docs/packages/overview#video-worker). For local docs preview: `nx start stereo-spot-docs`.
