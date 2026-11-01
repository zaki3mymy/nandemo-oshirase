output "api_endpoint" {
  description = "API Gateway endpoint URL"
  value       = module.notify.api_endpoint
}

output "api_key" {
  description = "API Key for authentication"
  value       = module.notify.api_key
  sensitive   = true
}

output "reminders_schedule_group_name" {
  description = "EventBridge Scheduler schedule group name for reminders"
  value       = module.notify.reminders_schedule_group_name
}

output "scheduler_role_arn" {
  description = "IAM role ARN used by EventBridge Scheduler to invoke the Lambda function"
  value       = module.notify.scheduler_role_arn
}
