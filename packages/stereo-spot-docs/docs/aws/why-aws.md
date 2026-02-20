---
sidebar_position: 1
---

# Why AWS first

The first cloud implementation is on **AWS** for practical reasons:

- **Ecosystem:** S3, SQS, DynamoDB, ECS Fargate, and SageMaker are a good fit for the job–worker pipeline, presigned URLs, and managed GPU inference.
- **SageMaker:** Managed GPU endpoints (e.g. for iw3/nunif stereo inference) with async invocation and S3 input/output keep the video-worker simple and avoid managing GPU instances ourselves.
- **nx-terraform:** The repo already uses the [nx-terraform](https://alexpialetski.github.io/nx-terraform/) plugin for Terraform; AWS provider and patterns are well established.

The pipeline is built on **cloud-agnostic abstractions** (job store, queues, object storage). Adding GCP or another cloud later means new Terraform and adapters; app and worker code stay the same.
