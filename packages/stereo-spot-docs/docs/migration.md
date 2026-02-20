---
sidebar_position: 7
---

# Migration path (e.g. GCP)

The pipeline uses **shared-types** and **cloud abstractions** (JobStore, SegmentCompletionStore, QueueSender/Receiver, ObjectStorage). Application and worker code stay the same. Adding another cloud is feasible with new Terraform and adapters.

## Same interfaces, new adapters

- **Compute:** Same container images; new Terraform would provision that cloud’s compute (e.g. Cloud Run, GKE). Inference endpoint would be that cloud’s managed GPU or your own service.
- **Queues:** Implement a new adapter behind the same queue interface (e.g. Pub/Sub for GCP). Reassembly trigger would use that cloud’s queue or equivalent.
- **Object storage:** Implement a new adapter (e.g. GCS); same SDK-style patterns.
- **Job and segment-completion store:** Implement new stores behind the existing interfaces (e.g. Firestore for GCP).

## Terraform

- Keep existing cloud packages (e.g. **aws-infra-setup**, **aws-infra**) for the current provider.
- Add new packages (e.g. **google-infra-setup**, **google-infra**) using that provider and the same nx-terraform pattern when migrating.

No change to app logic beyond configuration (env vars, endpoint URLs).

## See also

- [Why AWS first](/docs/aws/why-aws) — Rationale for the current AWS implementation.
- [AWS services and requirements](/docs/aws/services-and-requirements) — How each requirement maps to an AWS service.
