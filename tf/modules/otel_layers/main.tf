# OTel の Lambda レイヤーをまとめるモジュール。Lambda のモジュールは、output の layer_arns をそのまま layers に渡す。
#
# - 自前の Python のレイヤー（OTel の SDK・計装と、ハンドラーのラッパー）
# - コミュニティ製（opentelemetry-lambda）の Collector レイヤー
#   バージョンは https://github.com/open-telemetry/opentelemetry-lambda/releases で確認
#   （layer-collector/<version> のタグ）
#   新しいバージョンが出たら、.github/workflows/update-otel-lambda-layers.yml がこのファイルの ARN と
#   pyproject.toml・uv.lock の OTel の依存を一緒に上げる PR を作る（OTel の依存は、コミュニティの
#   Python 計装レイヤー（layer-python/<version>）と同じバージョンにそろえる。自前のレイヤーはそれを入れて作る）

locals {
  name_prefix = "${var.stage_name}-${var.project_name}"

  # コミュニティの Collector レイヤー
  collector_layer_arn = "arn:aws:lambda:ap-northeast-1:184161586896:layer:opentelemetry-collector-amd64-0_24_0:1"
}

# OTel の Python のレイヤー。コミュニティの Python 計装レイヤーの代わりに使う。
# コミュニティのレイヤーの .pyc は python3.14 用で、python3.13 の Lambda では使えず、コールドスタートのたびに
# コンパイルし直していたため、python3.13 用の .pyc を入れて自前で作る（docs/deployment.md を参照）。
# zip は scripts/build-otel-python-layer.py で作る（CI の terraform-plan と CD で、terraform の前に実行する）。
# 同じ uv.lock なら zip のハッシュは変わらないので、レイヤーは作り直されない
resource "aws_lambda_layer_version" "otel_python" {
  layer_name               = "${local.name_prefix}-otel-python"
  description              = "OTel SDK, instrumentations and handler wrapper (precompiled for python3.13) for ${local.name_prefix}"
  filename                 = var.otel_python_layer_zip_path
  source_code_hash         = filebase64sha256(var.otel_python_layer_zip_path)
  compatible_runtimes      = ["python3.13"]
  compatible_architectures = ["x86_64"]
}
