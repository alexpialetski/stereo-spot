# nx-terraform-metadata-start
# providers: aws, modules: terraform-aws-modules/vpc/aws@~> 5.0
# nx-terraform-metadata-end

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.32.1"
    }
  }
}

# Configure your providers here
# Example:
# provider "aws" {
#   region = var.region
# }


provider "aws" {
  region = var.region
}
