---
sidebar_position: 1
---

# Introduction

**StereoSpot** is a high-throughput, cost-optimized video processing system built as an Nx monorepo. It uses a job–worker pattern with cloud-agnostic abstractions for storage, queues, and compute.

## Prerequisites

To work with the repo (tests, lint, docs) you need:

| Tool | Purpose |
|------|---------|
| **Node.js** (v20+) and **npm** | Monorepo, Nx, and docs. Run `npm ci` from the workspace root. |
| **Nx** | Comes with the repo; use `npx nx` or `nx` (after install). No global install required. |
| **Python** (3.12) | Required for Python packages (workers, inference, shared-types). Nx runs `install-deps` when needed for test/serve. |

To **deploy and operate on AWS** you also need:

| Tool | Purpose |
|------|---------|
| **Terraform** | Provision and manage AWS infrastructure (see [AWS bring-up](/docs/aws/bring-up)). |
| **AWS CLI** | Runbooks (DLQ, ECS, SageMaker), smoke tests, and ad-hoc operations. Configure via credentials or env (see [Environment files](#environment-files) below). |
| **Docker** | Build and push app images (web-ui, media-worker, video-worker) to ECR. |

## Environment files

The project uses **two** `.env` files. Both are gitignored; do not commit them.

### Root `.env` (workspace root)

Used when you run **Terraform** or **AWS CLI** from your machine (e.g. `terraform apply`, `aws sqs receive-message`). Create this file yourself if you need to pass Terraform variables or AWS credentials via env.

**Typical shape:**

```bash
# Terraform variables (optional; can also use -var or tfvars)
TF_VAR_region=us-east-1
TF_VAR_account_id=123456789012

# AWS credentials (use one of: env vars below, or AWS_PROFILE, or default credential chain)
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_SESSION_TOKEN=

# Optional: disable pager for AWS CLI
AWS_PAGER=
```

When using an AWS profile instead of keys, you can leave `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` unset and set `AWS_PROFILE=your-profile`. Terraform and the AWS CLI read standard AWS env vars.

### `packages/aws-infra/.env` (generated)

Contains **Terraform outputs** (bucket names, queue URLs, table names, ECR URLs, ALB URL, etc.). You do **not** edit this file by hand.

- **How you get it:** Run **`nx run aws-infra:terraform-output`** after Terraform has been applied (see [Bringing the solution up (AWS)](/docs/aws/bring-up)).
- **Who uses it:** Deploy targets, smoke tests, and runbook commands. They load it automatically; you do not need to source it in your shell.

If you change infra (e.g. run `terraform-apply` again), re-run `nx run aws-infra:terraform-output` to refresh this file.

## Quick start

From the workspace root:

**Install dependencies:**

```bash
npm ci
```

Nx runs **install-deps** automatically when you run a target that needs it (e.g. test, serve). Run it yourself only to refresh the env (e.g. after pulling or changing dependencies).

**Run tests:**

```bash
nx run-many -t lint test
```

This runs lint and unit tests for all packages, including the integration package (moto-based, no real AWS).

**Preview this documentation site:**

```bash
nx start stereo-spot-docs
```

Then open the URL shown in the terminal (e.g. http://localhost:3000).

## What's in the docs

- **Architecture** — Monorepo layout, pipeline concepts, and shared interfaces (cloud-agnostic).
- **Packages** — Purpose, targets, and env vars for each package.
- **Testing** — Unit tests, integration tests, and smoke tests.
- **Runbooks** — Operations and recovery procedures.
- **AWS** — Current implementation: services, infrastructure, runbooks, and deploy.

## Next steps

- **Deploy on AWS:** See [Bringing the solution up (AWS)](/docs/aws/bring-up) for the one-time sequence (infra → .env → deploy → SageMaker).
- Read the [Architecture overview](/docs/architecture/overview) for monorepo layout and cloud abstractions.
- See [Testing](/docs/testing) for install-deps, unit tests, integration tests, and smoke test.
- Check [Runbooks](/docs/runbooks) for operations and recovery procedures.
