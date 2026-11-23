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

# OTel の Lambda レイヤー（コミュニティ製の Python 計装・Collector と、自前の計装）
module "otel_layers" {
  source = "../../modules/otel_layers"

  project_name = var.project_name
  stage_name   = "prod"

  # scripts/build-otel-instrumentations-layer.py の出力先
  otel_instrumentations_layer_zip_path = "${path.root}/../../../dist/otel-instrumentations-layer.zip"
}

# 自前の計装のレイヤーは、もとは notify モジュールの中で作っていた（レイヤーの名前は同じなので作り直されない）
moved {
  from = module.notify.aws_lambda_layer_version.otel_instrumentations
  to   = module.otel_layers.aws_lambda_layer_version.otel_instrumentations
}

module "notify" {
  source = "../../modules/notify"

  project_name          = var.project_name
  line_parameter_prefix = var.line_parameter_prefix
  log_level             = var.log_level
  stage_name            = "prod"

  otel_layer_arns = module.otel_layers.layer_arns

  # Grafana Cloud に送るための Authorization ヘッダーの値を置いた SSM パラメータ（このリポジトリの外で作る）
  grafana_otlp_auth_parameter = "/app/grafana/prod/otlp_auth"
}
