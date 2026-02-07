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
  default     = "nandemo-oshirase"
}

variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "ap-northeast-1"
}
