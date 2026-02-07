terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

module "notify" {
  source = "./modules"

  project_name       = var.project_name
  line_channel_token = var.line_channel_token
  line_user_id       = var.line_user_id
}
