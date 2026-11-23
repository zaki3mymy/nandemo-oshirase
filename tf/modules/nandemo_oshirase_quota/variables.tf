variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "stage_name" {
  description = "Environment name (dev, prod)"
  type        = string
}

variable "line_parameter_prefix" {
  description = "SSM Parameter Store path prefix that holds line_channel_token (e.g. /app/nandemo_oshirase/prod)"
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

variable "log_level" {
  description = "Log level for Lambda function (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
  type        = string
  default     = "INFO"
}

variable "grafana_otlp_endpoint" {
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

variable "schedule_enabled" {
  # dev と prod は LINE の上限を共有しているので、毎日取るのは prod だけにする（dev は CD で invoke するだけ）
  description = "Whether to invoke the function on a schedule (only in prod)"
  type        = bool
}

variable "schedule_expression" {
  description = "EventBridge Scheduler expression for the daily invocation"
  type        = string
  default     = "cron(55 23 * * ? *)"
}

variable "schedule_timezone" {
  description = "Time zone of schedule_expression"
  type        = string
  default     = "Asia/Tokyo"
}
