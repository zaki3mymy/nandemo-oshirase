output "layer_arns" {
  # Lambda の layers にこの順番で渡す。Python のレイヤーが AWS_LAMBDA_EXEC_WRAPPER（/opt/otel-handler）で
  # ハンドラーをラップし、Collector レイヤーが OTLP を受けて送る
  description = "ARNs of the OTel Lambda layers, in the order to pass to the Lambda function's layers"
  value       = [aws_lambda_layer_version.otel_python.arn, local.collector_layer_arn]
}
