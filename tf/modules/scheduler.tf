# 定時お知らせ用のリソース
#
# Terraformで管理するのは「入れ物」（スケジュールグループ・IAMロール）だけで、
# 個々のスケジュール（送信時刻・メッセージ）は `oshirase` CLI でAWS上に直接作成する。
# そのため、送信時刻やメッセージはリポジトリにもTerraform stateにも残らない。
#
# NOTE: API Gatewayのdeploymentは main.tf の filemd5 で再デプロイ判定しているため、
# API Gatewayと無関係なリソースはこのファイルに分けて置いている。

data "aws_caller_identity" "current" {}

# スケジュールグループ: CLIで作成するスケジュールはすべてこのグループに入れる
resource "aws_scheduler_schedule_group" "reminders" {
  name = "${local.name_prefix}-reminders"
}

# EventBridge Scheduler が Lambda を invoke するためのロール
resource "aws_iam_role" "scheduler" {
  name = "${local.name_prefix}-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "scheduler.amazonaws.com"
        }
        # confused deputy対策: このアカウントの reminders グループのスケジュールからのみ引き受け可能
        # aws:SourceArn にはスケジュールグループのARNを指定する（個々のスケジュールのARNは不可）
        # https://docs.aws.amazon.com/scheduler/latest/UserGuide/cross-service-confused-deputy-prevention.html
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
            "aws:SourceArn"     = aws_scheduler_schedule_group.reminders.arn
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke_lambda" {
  name = "${local.name_prefix}-scheduler-invoke-lambda"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "lambda:InvokeFunction"
        Effect = "Allow"
        Resource = [
          aws_lambda_function.notify.arn,
          "${aws_lambda_function.notify.arn}:*",
        ]
      }
    ]
  })
}

# 非同期invoke（Schedulerからの呼び出し）時の挙動
# API Gatewayからの呼び出しは同期invokeなので影響しない
resource "aws_lambda_function_event_invoke_config" "notify" {
  function_name = aws_lambda_function.notify.function_name

  # 失敗時のリトライは1回まで（二重送信のリスクを抑える）
  maximum_retry_attempts = 1
  # 1時間以上遅れたお知らせは送らない
  maximum_event_age_in_seconds = 3600
}
