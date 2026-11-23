# 定時実行（schedule_enabled = true の環境だけ）。
# oshirase CLI のスケジュールグループ（{env}-nandemo-oshirase-reminders）とは別のグループに入れる
# （CLI の list に出さないため）

resource "aws_scheduler_schedule_group" "quota" {
  count = var.schedule_enabled ? 1 : 0

  name = local.function_name
}

resource "aws_iam_role" "scheduler" {
  count = var.schedule_enabled ? 1 : 0

  name = "${local.function_name}-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "scheduler.amazonaws.com"
        }
        # confused deputy 対策: このアカウントのこのグループのスケジュールからのみ引き受けられる
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
            "aws:SourceArn"     = aws_scheduler_schedule_group.quota[0].arn
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "scheduler_invoke_lambda" {
  count = var.schedule_enabled ? 1 : 0

  name = "${local.function_name}-scheduler-invoke-lambda"
  role = aws_iam_role.scheduler[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "lambda:InvokeFunction"
        Effect = "Allow"
        Resource = [
          aws_lambda_function.quota.arn,
          "${aws_lambda_function.quota.arn}:*",
        ]
      }
    ]
  })
}

resource "aws_scheduler_schedule" "daily" {
  count = var.schedule_enabled ? 1 : 0

  name       = "daily"
  group_name = aws_scheduler_schedule_group.quota[0].name

  # その日に送った分まで含めて記録するため、日付が変わる直前に取る
  # （月が替わると LINE の値は 0 に戻るので、月末の日もほぼ1か月分の値が残る）
  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = var.schedule_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.quota.arn
    role_arn = aws_iam_role.scheduler[0].arn
    # イベントの中身は使わない
    input = jsonencode({})

    # Scheduler は Lambda を非同期で呼ぶ。Lambda の中のエラーのリトライは下の event_invoke_config で行い、
    # ここでは呼び出し自体が失敗したときだけリトライする
    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }
}

# 非同期 invoke（Scheduler からの呼び出し）が失敗したときのリトライ。値を取るだけなので、何度呼んでも害はない
resource "aws_lambda_function_event_invoke_config" "quota" {
  count = var.schedule_enabled ? 1 : 0

  function_name                = aws_lambda_function.quota.function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 3600
}
