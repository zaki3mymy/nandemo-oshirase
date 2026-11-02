variable "line_parameter_prefix" {
  description = "SSM Parameter Store path prefix that holds line_channel_token and line_user_id"
  type        = string
  default     = "/app/nandemo_oshirase/dev"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "nandemo-oshirase"
}

variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "ap-northeast-1"
}

variable "log_level" {
  description = "Log level for Lambda function (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
  type        = string
  default     = "INFO"
}
