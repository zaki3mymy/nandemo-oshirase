output "api_endpoint" {
  description = "API Gateway endpoint URL"
  value       = "${aws_api_gateway_stage.prod.invoke_url}/notify"
}

output "api_key" {
  description = "API Key for authentication"
  value       = aws_api_gateway_api_key.api_key.value
  sensitive   = true
}

output "lambda_function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.notify.function_name
}

output "lambda_function_arn" {
  description = "Lambda function ARN"
  value       = aws_lambda_function.notify.arn
}
