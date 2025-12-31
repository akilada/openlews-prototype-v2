# Root Terragrunt Configuration
# File: infrastructure/terragrunt.hcl

terraform_version_constraint  = ">= 1.6.0"
terragrunt_version_constraint = ">= 0.55.0"

locals {
  project_name = "openlews"
  aws_region   = "ap-southeast-2"

  common_tags = {
    Project    = "OpenLEWS"
    ManagedBy  = "Terragrunt"
    Repository = "openlews-prototype"
  }
}

remote_state {
  backend = "s3"

  generate = {
    path      = "backend.tf"
    if_exists = "overwrite"
  }

  config = {
    bucket         = "openlews-terraform-state-${get_aws_account_id()}"
    key            = "${path_relative_to_include()}/terraform.tfstate"
    region         = local.aws_region
    encrypt        = true
    dynamodb_table = "openlews-terraform-locks"

    s3_bucket_tags = {
      Name      = "OpenLEWS Terraform State"
      Project   = "OpenLEWS"
      ManagedBy = "Terragrunt"
    }

    dynamodb_table_tags = {
      Name      = "OpenLEWS Terraform Lock Table"
      Project   = "OpenLEWS"
      ManagedBy = "Terragrunt"
    }
  }
}

generate "versions" {
  path      = "versions.tf"
  if_exists = "overwrite"
  contents  = <<EOF
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }
}
EOF
}

generate "provider" {
  path      = "provider.tf"
  if_exists = "overwrite"
  contents  = <<EOF
provider "aws" {
  region = var.aws_region

  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_credentials_validation = false

  default_tags {
    tags = var.tags
  }
}
EOF
}

retryable_errors = [
  "(?s).*Error.*rate limit.*",
  "(?s).*RequestLimitExceeded.*",
  "(?s).*Throttling.*",
]

skip = false
