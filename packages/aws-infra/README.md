# Terraform: aws-infra

Provisions S3, SQS, DynamoDB, ECS (web-ui, media-worker, video-worker), ECR, CodeBuild, SageMaker, ALB. Uses backend from aws-infra-setup.

**Main targets:** `terraform-init`, `terraform-plan`, `terraform-apply`, `terraform-output`.

**Full documentation:** [AWS infrastructure](https://alexpialetski.github.io/stereo-spot/docs/aws/infrastructure) and [Packages → aws-infra](https://alexpialetski.github.io/stereo-spot/docs/packages/overview#aws-infra). For local docs preview: `nx start stereo-spot-docs`.
