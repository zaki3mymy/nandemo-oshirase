output "api_endpoint" {
  description = "API Gateway endpoint URL"
  value       = module.notify.api_endpoint
}

output "api_key" {
  description = "API Key for authentication"
  value       = module.notify.api_key
  sensitive   = true
}
