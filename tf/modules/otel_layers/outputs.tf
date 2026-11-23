output "layer_arns" {
  # Lambda の layers にこの順番で渡す。Python 計装レイヤーが AWS_LAMBDA_EXEC_WRAPPER（/opt/otel-handler）で
  # ハンドラーをラップし、Collector レイヤーが OTLP を受けて送る。
  # 自前の計装のレイヤーは、コミュニティのレイヤーのあとに重ねる（どれも /opt/python に展開される）
  description = "ARNs of the OTel Lambda layers, in the order to pass to the Lambda function's layers"
  value       = concat(local.community_layer_arns, [aws_lambda_layer_version.otel_instrumentations.arn])
}
