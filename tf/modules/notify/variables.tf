variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "line_parameter_prefix" {
  description = "SSM Parameter Store path prefix that holds line_channel_token and line_user_id (e.g. /app/nandemo_oshirase/prod)"
  type        = string

  validation {
    condition     = can(regex("^/[^ ]*[^/]$", var.line_parameter_prefix))
    error_message = "line_parameter_prefix must start with '/' and must not end with '/'."
  }
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention in days"
  type        = number
  default     = 14
}

variable "memory_size" {
  description = "Memory size of the Lambda function in MB"
  type        = number
  default     = 256
}

variable "log_level" {
  description = "Log level for Lambda function (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
  type        = string
  default     = "INFO"
}

variable "stage_name" {
  description = "API Gateway stage name"
  type        = string
}

variable "grafana_otlp_endpoint" {
  # Grafana Cloud のスタックの OTLP の URL に /otlp を付けたもの。
  # otlphttp exporter はこの後ろに /v1/traces・/v1/metrics を付けて送る
  description = "Grafana Cloud の OTLP の送信先（スタックの otlp_url に /otlp を付けたもの）"
  type        = string
  default     = "https://otlp-gateway-prod-ap-northeast-0.grafana.net/otlp"
}

variable "grafana_otlp_auth_parameter" {
  description = "Grafana Cloud に OTLP で送るための Authorization ヘッダーの値を置いた SSM パラメータの名前（例: /app/grafana/prod/otlp_auth）"
  type        = string
}

variable "otel_layer_arns" {
  description = "ARNs of the OTel Lambda layers, in order (the layer_arns output of tf/modules/otel_layers)"
  type        = list(string)
}
