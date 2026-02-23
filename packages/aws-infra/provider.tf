# nx-terraform-metadata-start
# providers: aws,local, modules: terraform-aws-modules/vpc/aws@~> 5.0
# nx-terraform-metadata-end

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.32.1"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    external = {
      source  = "hashicorp/external"
      version = "~> 2.0"
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

  default_tags {
    tags = {
      App = var.name_prefix
    }
  }
}

provider "local" {}
