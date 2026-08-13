locals {
  name_prefix     = "${var.stage_name}-${var.project_name}"
  lambda_code_dir = "${path.module}/../../src/nandemo_oshirase"
}

# archive_fileの`source_dir`と`source`は同時指定できないため、
# `source_dir`配下のファイルを`fileset`で列挙し、collector.yamlと合わせて`source`で1つのzipにまとめる
data "archive_file" "lambda_zip" {
  type        = "zip"
  output_path = "${path.module}/lambda.zip"

  dynamic "source" {
    for_each = fileset(local.lambda_code_dir, "**")
    content {
      content  = file("${local.lambda_code_dir}/${source.value}")
      filename = source.value
    }
  }

  source {
    content  = file("${path.module}/../../collector.yaml")
    filename = "collector.yaml"
  }
}

# IAM Role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = "${local.name_prefix}-lambda-role"

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

resource "aws_iam_role_policy_attachment" "lambda_xray" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy_attachment" "lambda_cloudwatch_metrics" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

# Lambda Function
resource "aws_lambda_function" "notify" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "${local.name_prefix}-function"
  role             = aws_iam_role.lambda_role.arn
  handler          = "lambda_function.lambda_handler"
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  runtime          = "python3.13"
  timeout          = 30

  # OTel Lambdaレイヤー: Python計装レイヤー + OTel Collectorレイヤー
  # バージョンはリリースページ（https://github.com/open-telemetry/opentelemetry-lambda/releases）で
  # ap-northeast-1 向けの最新版を確認のうえ、必要に応じて更新すること
  # AWS_LAMBDA_EXEC_WRAPPER（下記environment）でPython計装レイヤーがlambda_handlerをラップする
  layers = [
    "arn:aws:lambda:ap-northeast-1:184161586896:layer:opentelemetry-python-0_21_0:1",
    "arn:aws:lambda:ap-northeast-1:184161586896:layer:opentelemetry-collector-amd64-0_23_0:1",
  ]

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = {
      LINE_CHANNEL_TOKEN                                = var.line_channel_token
      LINE_USER_ID                                      = var.line_user_id
      LOG_LEVEL                                         = var.log_level
      AWS_LAMBDA_EXEC_WRAPPER                           = "/opt/python/otel-handler"
      OPENTELEMETRY_COLLECTOR_CONFIG_URI                = "/var/task/collector.yaml"
      OTEL_SERVICE_NAME                                 = "nandemo-oshirase"
      OTEL_TRACES_EXPORTER                              = "otlp"
      OTEL_METRICS_EXPORTER                             = "otlp"
      OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE = "DELTA"
    }
  }
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.notify.function_name}"
  retention_in_days = var.log_retention_days
}

# IAM Role for API Gateway CloudWatch Logging
resource "aws_iam_role" "api_gateway_cloudwatch" {
  name = "${local.name_prefix}-apigw-cloudwatch-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "apigateway.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "api_gateway_cloudwatch" {
  role       = aws_iam_role.api_gateway_cloudwatch.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}

resource "aws_api_gateway_account" "main" {
  cloudwatch_role_arn = aws_iam_role.api_gateway_cloudwatch.arn
}

# CloudWatch Log Group for API Gateway access logs
resource "aws_cloudwatch_log_group" "api_gateway_logs" {
  name              = "API-Gateway-Execution-Logs_${aws_api_gateway_rest_api.api.id}/${var.stage_name}"
  retention_in_days = var.log_retention_days
}

# API Gateway REST API
resource "aws_api_gateway_rest_api" "api" {
  name        = "${local.name_prefix}-api"
  description = "API for LINE notification service"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

# API Gateway Resource: /notify
resource "aws_api_gateway_resource" "notify" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "notify"
}

# API Gateway Method: POST /notify
resource "aws_api_gateway_method" "notify_post" {
  rest_api_id      = aws_api_gateway_rest_api.api.id
  resource_id      = aws_api_gateway_resource.notify.id
  http_method      = "POST"
  authorization    = "NONE"
  api_key_required = true
}

# API Gateway Integration with Lambda
resource "aws_api_gateway_integration" "lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.notify.id
  http_method             = aws_api_gateway_method.notify_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.notify.invoke_arn
}

# Lambda Permission for API Gateway
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.notify.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.api.execution_arn}/*/*"
}

# API Gateway Resource: /webhook
resource "aws_api_gateway_resource" "webhook" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "webhook"
}

# API Gateway Method: POST /webhook (APIキー不要 - LINEプラットフォームから送信される)
resource "aws_api_gateway_method" "webhook_post" {
  rest_api_id      = aws_api_gateway_rest_api.api.id
  resource_id      = aws_api_gateway_resource.webhook.id
  http_method      = "POST"
  authorization    = "NONE"
  api_key_required = false
}

# API Gateway Integration: POST /webhook → Lambda
resource "aws_api_gateway_integration" "webhook_integration" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.webhook.id
  http_method             = aws_api_gateway_method.webhook_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.notify.invoke_arn
}

# API Gateway Resource: /docs
resource "aws_api_gateway_resource" "docs" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "docs"
}

# API Gateway Method: GET /docs (APIキー不要)
resource "aws_api_gateway_method" "docs_get" {
  rest_api_id      = aws_api_gateway_rest_api.api.id
  resource_id      = aws_api_gateway_resource.docs.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = false
}

# API Gateway Integration: GET /docs → Lambda
resource "aws_api_gateway_integration" "docs_integration" {
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.docs.id
  http_method             = aws_api_gateway_method.docs_get.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.notify.invoke_arn
}

# API Gateway Deployment
resource "aws_api_gateway_deployment" "deployment" {
  depends_on = [
    aws_api_gateway_integration.lambda_integration,
    aws_api_gateway_integration.webhook_integration,
    aws_api_gateway_integration.docs_integration,
  ]

  rest_api_id = aws_api_gateway_rest_api.api.id

  triggers = {
    redeployment = filemd5("${path.module}/main.tf")
  }
  lifecycle {
    create_before_destroy = true
  }
}

# API Gateway Stage
resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.deployment.id
  rest_api_id   = aws_api_gateway_rest_api.api.id
  stage_name    = var.stage_name

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway_logs.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      httpMethod     = "$context.httpMethod"
      resourcePath   = "$context.resourcePath"
      status         = "$context.status"
      responseLength = "$context.responseLength"
      requestTime    = "$context.requestTime"
    })
  }

  depends_on = [aws_api_gateway_account.main]
}

resource "aws_api_gateway_method_settings" "all" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  stage_name  = aws_api_gateway_stage.prod.stage_name
  method_path = "*/*"

  settings {
    logging_level      = "INFO"
    data_trace_enabled = false
    metrics_enabled    = true
  }
}

# API Key
resource "aws_api_gateway_api_key" "api_key" {
  name    = "${local.name_prefix}-api-key"
  enabled = true
}

# Usage Plan
resource "aws_api_gateway_usage_plan" "usage_plan" {
  name = "${local.name_prefix}-usage-plan"

  api_stages {
    api_id = aws_api_gateway_rest_api.api.id
    stage  = aws_api_gateway_stage.prod.stage_name
  }
}

# Usage Plan Key
resource "aws_api_gateway_usage_plan_key" "usage_plan_key" {
  key_id        = aws_api_gateway_api_key.api_key.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.usage_plan.id
}
