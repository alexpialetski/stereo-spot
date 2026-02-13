# Terraform Module: aws-infra

This is a stateful Terraform module that uses the AWS S3 backend configuration from the `aws-infra-setup` project.

## Backend Configuration

This module uses the `backend.config` file from the `aws-infra-setup` project. The backend configuration is automatically referenced during `terraform init`.

## Usage

This module manages its own Terraform state using the AWS S3 remote backend.

## Variables

See `variables.tf` for input variable definitions.

## Outputs

See `outputs.tf` for output value definitions.
