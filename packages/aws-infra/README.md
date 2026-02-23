# Terraform: aws-infra

Provisions S3, SQS, DynamoDB, ECS (web-ui, media-worker, video-worker), ECR, CodeBuild, SageMaker, ALB. Uses backend from aws-infra-setup.

**Main targets:** `terraform-init`, `terraform-plan`, `terraform-apply`, `terraform-output`. **terraform-apply** requires Python 3 with `pip install cryptography` for the VAPID PEM-to-key script.

**ALB HTTPS (optional):** By default the ALB serves HTTP only. To enable HTTPS (and HTTP-to-HTTPS redirect) so the Service Worker works in a trusted context: (1) Apply once to create the ALB, then run `nx run aws-infra:terraform-output`. (2) Place **`alb-certificate.pem`** and **`alb-private-key.pem`** at the **project root** (exact names). Generate them however you like; Terraform only requires the filenames and location. (3) Apply again; Terraform reads the cert files and creates the HTTPS listener. The cert files are gitignored.

**Suggested: mkcert on Windows** (trusted in browser): Install [mkcert](https://github.com/FiloSottile/mkcert) (e.g. `choco install mkcert`), run `mkcert -install` once, then from the project root run: `mkcert -cert-file alb-certificate.pem -key-file alb-private-key.pem "<ALB_DNS>"`. Use the ALB DNS name from `packages/aws-infra/.env` (variable **WEB_UI_ALB_DNS_NAME**) after terraform-output.

**Full documentation:** [AWS infrastructure](https://alexpialetski.github.io/stereo-spot/docs/aws/infrastructure) and [Packages → aws-infra](https://alexpialetski.github.io/stereo-spot/docs/packages/overview#aws-infra). For local docs preview: `nx start stereo-spot-docs`.
