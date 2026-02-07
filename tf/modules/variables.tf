variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

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

variable "log_retention_days" {
  description = "CloudWatch Logs retention in days"
  type        = number
  default     = 14
}
