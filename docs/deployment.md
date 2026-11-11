# デプロイ

mainブランチへのマージ時にGitHub Actionsで自動デプロイされます。

## 前提：API Gateway のアカウント設定

API Gateway がログを CloudWatch Logs に書くためのロールは、AWS のアカウントとリージョンに1つしかない設定のため、このリポジトリではなく [zaki3mymy/account-baseline](https://github.com/zaki3mymy/account-baseline) で管理しています。この設定がないとステージのアクセスログを有効にできず apply が失敗するので、新しいアカウント・リージョンにデプロイするときは account-baseline を先に apply してください。

## GitHub Secrets

以下のシークレットを設定してください:

| Secret | 説明 |
|--------|------|
| `AWS_ROLE_ARN` | OIDC認証用のIAMロールARN |
| `TERRAFORM_STATE_BUCKET` | Terraform state用S3バケット名 |

## LINE の認証情報（SSM Parameter Store）

LINE のチャネルアクセストークンと通知先のユーザーIDは、環境ごとに SSM Parameter Store の SecureString（AWS管理キー `aws/ssm`）に置き、Lambda が実行時に読み込みます。値は Terraform の state、Lambda の環境変数、GitHub の Secrets のいずれにも置きません。パラメータは Terraform の外で作成してください。

| 環境 | パラメータ |
|---|---|
| dev | `/app/nandemo_oshirase/dev/line_channel_token`、`/app/nandemo_oshirase/dev/line_user_id` |
| prod | `/app/nandemo_oshirase/prod/line_channel_token`、`/app/nandemo_oshirase/prod/line_user_id` |

```bash
aws ssm put-parameter --type SecureString --name /app/nandemo_oshirase/prod/line_channel_token --value '...'
aws ssm put-parameter --type SecureString --name /app/nandemo_oshirase/prod/line_user_id --value '...'
```

- パス（`/app/nandemo_oshirase/<env>`）は、Terraform の変数 `line_parameter_prefix` で変更できます。
- Lambda は読み込んだ値を15分間キャッシュします。値を更新した場合、デプロイし直さなくても最長15分で反映されます。
- ローカル実行（podman-compose）では、`.env.local` の `LINE_CHANNEL_TOKEN` と `LINE_USER_ID` が直接使われます（SSM は参照しません）。

## 本番環境のOTelテレメトリ

本番Lambdaには OTel の Python計装レイヤーと Collectorレイヤーをアタッチしており、認証はLambda実行ロールのIAM権限（`AWSXRayDaemonWriteAccess` / `CloudWatchAgentServerPolicy`）で行います。追加のシークレット設定は不要です。

トレース・メトリクスの転送先とCollectorの設定は `src/nandemo_oshirase/collector.yaml` にまとめており、デプロイ時にLambdaのデプロイパッケージへ含まれます。

| テレメトリ | バックエンド | 確認方法 |
|---|---|---|
| トレース | AWS X-Ray | X-Ray コンソール / CloudWatch ServiceLens |
| メトリクス | Amazon CloudWatch (EMF) | CloudWatch メトリクス（namespace: `NandemoOshirase`） |


## CLI の実行に必要な IAM 権限

CLI を実行する AWS 認証情報には、次の権限が必要です。

| 権限 | 対象 |
|---|---|
| `scheduler:CreateSchedule` / `GetSchedule` / `UpdateSchedule` / `DeleteSchedule` | `arn:aws:scheduler:*:*:schedule/{env}-nandemo-oshirase-reminders/*` |
| `scheduler:ListSchedules` | `*` |
| `iam:PassRole` | `{env}-nandemo-oshirase-scheduler-role` |
| `sts:GetCallerIdentity` | `*` |
| `lambda:InvokeFunction`（`send` を使う場合のみ） | `{env}-nandemo-oshirase-function` |
