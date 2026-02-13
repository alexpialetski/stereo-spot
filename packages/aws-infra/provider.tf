# nx-terraform-metadata-start
# providers: aws
# nx-terraform-metadata-end


terraform {
  required_providers {
    # Add your required providers here
    # Example:
    # aws = {
    #   source  = "hashicorp/aws"
    #   version = "~> 6.0"
    # }

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
