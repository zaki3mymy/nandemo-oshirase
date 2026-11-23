# LINE Messaging API の当月の利用数と上限を取得し、OTel のメトリクスとして Grafana Cloud に送る Lambda。
# コードは src/nandemo_oshirase_quota。dev と prod の両方に作るが、定時実行（schedule.tf）は
# schedule_enabled = true の環境（prod）だけ。dev は CD のデプロイのあとに invoke して確かめるだけ。
# dev と prod は同じ LINE チャネルを使っているので、取れる値は同じ（Grafana では prod の値だけを使う）

locals {
  name_prefix   = "${var.stage_name}-${var.project_name}"
  function_name = "${local.name_prefix}-quota"

  # 送信の Lambda と同じ SSM パラメータ（Terraform の外で作る。値を state に残さないため data では読まない）
  line_channel_token_parameter = "${var.line_parameter_prefix}/line_channel_token"
}

# Grafana Cloud に OTLP で送るための Authorization ヘッダーの値。
# Collector レイヤーは SSM を読めないので、ここで読んで Lambda の環境変数に渡す（送信の Lambda と同じ）
data "aws_ssm_parameter" "grafana_otlp_auth" {
  name = var.grafana_otlp_auth_parameter
}

data "aws_region" "current" {}

data "aws_caller_identity" "current" {}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../../../src/nandemo_oshirase_quota"
  output_path = "${path.module}/lambda.zip"
}

resource "aws_iam_role" "lambda_role" {
  name = "${local.function_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# チャネルアクセストークンだけを読む。AWS管理キー（aws/ssm）の SecureString なので kms:Decrypt は不要
resource "aws_iam_role_policy" "lambda_read_line_channel_token" {
  name = "${local.function_name}-read-line-channel-token"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action   = "ssm:GetParameter"
        Effect   = "Allow"
        Resource = "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${local.line_channel_token_parameter}"
      }
    ]
  })
}

resource "aws_lambda_function" "quota" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = local.function_name
  role             = aws_iam_role.lambda_role.arn
  handler          = "lambda_function.lambda_handler"
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  runtime          = "python3.13"
  timeout          = 30

  # OTel の Lambda レイヤー（Python 計装・Collector・自前の計装）。tf/modules/otel_layers で作り、順番もそこで決める。
  # コレクターは OTLP を受けて、Grafana Cloud に otlphttp で送る（collector.yaml）
  layers = var.otel_layer_arns

  # X-Ray にはトレースを送らない（Grafana Cloud に送る）
  tracing_config {
    mode = "PassThrough"
  }

  environment {
    variables = {
      LINE_CHANNEL_TOKEN_PARAM           = local.line_channel_token_parameter
      LOG_LEVEL                          = var.log_level
      AWS_LAMBDA_EXEC_WRAPPER            = "/opt/otel-handler"
      OPENTELEMETRY_COLLECTOR_CONFIG_URI = "/var/task/collector.yaml"
      OTEL_SERVICE_NAME                  = "nandemo-oshirase-quota"
      # 環境（dev・prod）。Grafana では prod の値だけを使う（dev と prod で同じ値が届くため、足さない）
      OTEL_RESOURCE_ATTRIBUTES = "deployment.environment.name=${var.stage_name},deployment.environment=${var.stage_name}"
      OTEL_TRACES_EXPORTER     = "otlp"
      OTEL_METRICS_EXPORTER    = "otlp"
      # ログは実行の終わりに lambda_function.py で flush する
      OTEL_LOGS_EXPORTER          = "otlp"
      GRAFANA_CLOUD_OTLP_ENDPOINT = var.grafana_otlp_endpoint
      GRAFANA_CLOUD_OTLP_AUTH     = data.aws_ssm_parameter.grafana_otlp_auth.value
    }
  }
}

resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.quota.function_name}"
  retention_in_days = var.log_retention_days
}
