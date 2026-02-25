# Terraform: aws-infra

Provisions S3, SQS, DynamoDB, ECS (web-ui, media-worker, video-worker), ECR, CodeBuild, SageMaker, ALB. Uses backend from aws-infra-setup.

**Main targets:** `terraform-init`, `terraform-plan`, `terraform-apply`, `terraform-output`. **terraform-apply** requires Python 3 with `pip install cryptography` for the VAPID PEM-to-key script.

**ALB HTTPS (optional):** By default the ALB serves HTTP only. To enable HTTPS: (1) Apply once, run **terraform-output**. (2) Generate cert and key (e.g. [mkcert](https://github.com/FiloSottile/mkcert); default paths **`alb-certificate.pem`** and **`alb-private-key.pem`** at the project root). (3) Run **`PLATFORM=aws nx run stereo-spot:update-alb-certificates`** from the workspace root (optionally `--cert-file` / `--key-file`). This imports the cert into ACM and sets **`TF_VAR_load_balancer_certificate_id`** in the **root** `.env`. (4) Apply again; Terraform attaches the cert to the ALB. Cert content is not in Terraform state.

**Terraform variables and secrets:** Set feature flags and Terraform inputs in the **root** `.env` (e.g. **`TF_VAR_enable_youtube_ingest`**, **`TF_VAR_load_balancer_certificate_id`**). Root Nx targets **update-hf-token**, **update-ytdlp-cookies**, and **update-alb-certificates** (run with **PLATFORM=aws**) push secrets or import certs and can update root `.env`. See [Bringing the solution up](https://alexpialetski.github.io/stereo-spot/docs/aws/bring-up) in the docs.

**Full documentation:** [AWS infrastructure](https://alexpialetski.github.io/stereo-spot/docs/aws/infrastructure) and [Packages → aws-infra](https://alexpialetski.github.io/stereo-spot/docs/packages/overview#aws-infra). For local docs preview: `nx start stereo-spot-docs`.
