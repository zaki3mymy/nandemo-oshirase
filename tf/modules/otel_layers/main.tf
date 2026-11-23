# OTel の Lambda レイヤーをまとめるモジュール。Lambda のモジュールは、output の layer_arns をそのまま layers に渡す。
#
# - コミュニティ製（opentelemetry-lambda）の Python 計装レイヤーと Collector レイヤー
#   バージョンは https://github.com/open-telemetry/opentelemetry-lambda/releases で確認
#   （layer-python/<version>・layer-collector/<version> のタグ）
#   新しいバージョンが出たら、.github/workflows/update-otel-lambda-layers.yml がこのファイルの ARN と
#   pyproject.toml・uv.lock の OTel の依存を一緒に上げる PR を作る（ローカルと本番をそろえる。
#   自前の計装のレイヤーも uv.lock のバージョンで作る）。手で上げるときも、両方を同じバージョンにする
# - 自前の計装のレイヤー（コミュニティの Python 計装レイヤーに無い計装を足す）

locals {
  name_prefix = "${var.stage_name}-${var.project_name}"

  # コミュニティのレイヤー（Python 計装・Collector の順）
  community_layer_arns = [
    "arn:aws:lambda:ap-northeast-1:184161586896:layer:opentelemetry-python-0_22_0:1",
    "arn:aws:lambda:ap-northeast-1:184161586896:layer:opentelemetry-collector-amd64-0_24_0:1",
  ]
}

# コミュニティの Python 計装レイヤーに無い計装を、自前で足すレイヤー。
#   - opentelemetry-instrumentation-urllib: LINE API の呼び出しの span を出す
#   - opentelemetry-instrumentation-logging: logging のログを OTel のログとして送る
# zip は scripts/build-otel-instrumentations-layer.py で作る（CI の terraform-plan と CD で、terraform の前に実行する）。
# 同じバージョンなら zip のハッシュは変わらないので、レイヤーは作り直されない
resource "aws_lambda_layer_version" "otel_instrumentations" {
  layer_name          = "${local.name_prefix}-otel-instrumentations"
  description         = "OTel instrumentations missing from the community layer (urllib, logging) for ${local.name_prefix}"
  filename            = var.otel_instrumentations_layer_zip_path
  source_code_hash    = filebase64sha256(var.otel_instrumentations_layer_zip_path)
  compatible_runtimes = ["python3.13"]
}
