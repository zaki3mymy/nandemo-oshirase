terraform {
  required_version = ">= 1.17.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  # `terraform init`のときに`-backend-config`で以下の値を設定する
  # -backend-config="bucket=<BUCKET_NAME>"
  # -backend-config="key=nandemo-oshirase/terraform.tfstate"
  # -backend-config="region=ap-northeast-1"
  backend "s3" {
  }
}

provider "aws" {
  region = var.aws_region
}

# OTel の Lambda レイヤー（自前の Python のレイヤーと、コミュニティ製の Collector）
module "otel_layers" {
  source = "../../modules/otel_layers"

  project_name = var.project_name
  stage_name   = "prod"

  # scripts/build-otel-python-layer.py の出力先
  otel_python_layer_zip_path = "${path.root}/../../../dist/otel-python-layer.zip"
}

module "notify" {
  source = "../../modules/notify"

  project_name          = var.project_name
  line_parameter_prefix = var.line_parameter_prefix
  log_level             = var.log_level
  stage_name            = "prod"
  memory_size           = 256

  otel_layer_arns = module.otel_layers.layer_arns

  # Grafana Cloud に送るための Authorization ヘッダーの値を置いた SSM パラメータ（このリポジトリの外で作る）
  grafana_otlp_auth_parameter = "/app/grafana/prod/otlp_auth"
}

# LINE の当月の利用数と上限を取得して、Grafana Cloud にメトリクスを送る Lambda。
# 毎日 23:55（Asia/Tokyo）に取得する
module "nandemo_oshirase_quota" {
  source = "../../modules/nandemo_oshirase_quota"

  project_name          = var.project_name
  line_parameter_prefix = var.line_parameter_prefix
  log_level             = var.log_level
  stage_name            = "prod"
  memory_size           = 256

  otel_layer_arns = module.otel_layers.layer_arns

  grafana_otlp_auth_parameter = "/app/grafana/prod/otlp_auth"

  schedule_enabled = true
}
