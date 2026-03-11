variable "line_channel_token" {
  description = "LINE Messaging API Channel Access Token"
  type        = string
  sensitive   = true
}

variable "line_user_id" {
  description = "LINE User ID to send messages to"
  type        = string
  sensitive   = true
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "nandemo-oshirase-dev"
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
