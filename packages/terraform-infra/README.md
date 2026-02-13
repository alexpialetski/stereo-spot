# Terraform Module: terraform-infra

This is a stateful Terraform module that uses the AWS S3 backend configuration from the `terraform-setup` project.

## Backend Configuration

This module uses the `backend.config` file from the `terraform-setup` project. The backend configuration is automatically referenced during `terraform init`.

## Usage

This module manages its own Terraform state using the AWS S3 remote backend.

## Variables

See `variables.tf` for input variable definitions.

## Outputs

See `outputs.tf` for output value definitions.

