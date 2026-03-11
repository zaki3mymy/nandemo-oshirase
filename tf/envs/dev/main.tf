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

  # `terraform init`のときに`-backend-config`で以下の値を設定する
  # -backend-config="bucket=<BUCKET_NAME>"
  # -backend-config="key=nandemo-oshirase-dev/terraform.tfstate"
  # -backend-config="region=ap-northeast-1"
  backend "s3" {
  }
}

provider "aws" {
  region = var.aws_region
}

module "notify" {
  source = "../../modules"

  project_name       = var.project_name
  line_channel_token = var.line_channel_token
  line_user_id       = var.line_user_id
  log_level          = var.log_level
  stage_name         = "dev"
}
