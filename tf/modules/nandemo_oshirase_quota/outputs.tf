output "lambda_function_name" {
  description = "Name of the Lambda function that records the LINE message quota"
  value       = aws_lambda_function.quota.function_name
}
