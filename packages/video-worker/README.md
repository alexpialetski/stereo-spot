# Video worker

Consumes video-worker and segment-output queues; invokes inference (SageMaker/HTTP/stub) and triggers reassembly when segments complete.

**Main targets:** `test`, `lint`, `build`, `deploy`.

**Full documentation:** [Packages → video-worker](https://alexpialetski.github.io/stereo-spot/docs/packages/overview#video-worker). For local docs preview: `nx start stereo-spot-docs`.
