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

## デプロイ用の IAM ロールに必要な権限

`AWS_ROLE_ARN` のロールには、Terraform が作るリソースを管理する権限が必要です。[再送](architecture.md#再送冪等性)のために DynamoDB のテーブル（`{env}-nandemo-oshirase-retry-keys`）を作ります。ロールの権限を絞っている場合は、`dynamodb:CreateTable`、`DescribeTable`、`UpdateTable`、`DeleteTable`、`UpdateTimeToLive`、`DescribeTimeToLive`、`DescribeContinuousBackups`、`ListTagsOfResource`、`TagResource`、`UntagResource` も許可してください。

LINE の利用数を取得する Lambda（[アーキテクチャ](architecture.md#line-の利用数の監視)）のために、`{env}-nandemo-oshirase-quota` の関数・IAM ロール・ロググループを作ります。prod では、さらにスケジュールグループ（`prod-nandemo-oshirase-quota`）・スケジュール・Scheduler 用の IAM ロールを作ります。また、CD は apply のあとにこの関数を1回 invoke して動作を確かめるので、ロールの権限を絞っている場合は `lambda:InvokeFunction`（`{env}-nandemo-oshirase-quota`）も許可してください。

## LINE の認証情報（SSM Parameter Store）

LINE のチャネルアクセストークンと通知先のユーザーIDは、環境ごとに SSM Parameter Store の SecureString（AWS管理キー `aws/ssm`）に置き、Lambda が実行時に読み込みます。値は Terraform の state、Lambda の環境変数、GitHub の Secrets のいずれにも置きません。パラメータは Terraform の外で作成してください。

| 環境 | パラメータ |
|---|---|
| dev | `/app/nandemo_oshirase/dev/line_channel_token`、`/app/nandemo_oshirase/dev/line_user_id` |
| prod | `/app/nandemo_oshirase/prod/line_channel_token`、`/app/nandemo_oshirase/prod/line_user_id` |

LINE の利用数を取得する Lambda（`{env}-nandemo-oshirase-quota`）も、同じ環境の `line_channel_token` を読みます（`line_user_id` は読みません）。

```bash
aws ssm put-parameter --type SecureString --name /app/nandemo_oshirase/prod/line_channel_token --value '...'
aws ssm put-parameter --type SecureString --name /app/nandemo_oshirase/prod/line_user_id --value '...'
```

- パス（`/app/nandemo_oshirase/<env>`）は、Terraform の変数 `line_parameter_prefix` で変更できます。
- Lambda は読み込んだ値を15分間キャッシュします。値を更新した場合、デプロイし直さなくても最長15分で反映されます。
- ローカル実行（podman-compose）では、`.env.local` の `LINE_CHANNEL_TOKEN` と `LINE_USER_ID` が直接使われます（SSM は参照しません）。

## 本番環境のOTelテレメトリ

Lambdaには、OTel の Python のレイヤー（自前。下の「OTel の Python のレイヤー」を参照）と、Collectorレイヤー（[opentelemetry-lambda](https://github.com/open-telemetry/opentelemetry-lambda) のコミュニティ製）をアタッチしています。アプリが送ったトレース・メトリクス・ログを Collector が受け取り、Grafana Cloud に OTLP で送ります。

| テレメトリ | バックエンド | 確認方法 |
|---|---|---|
| トレース | Grafana Cloud（Tempo） | Grafana の Explore（データソース: Tempo） |
| メトリクス | Grafana Cloud（Prometheus 互換） | Grafana の Explore（データソース: Prometheus） |
| ログ | Grafana Cloud（Loki） | Grafana の Explore（データソース: Loki）。`{service_name="nandemo-oshirase"}` で絞り込む |

- Collectorの設定は `src/nandemo_oshirase/collector.yaml` にまとめており、デプロイ時にLambdaのデプロイパッケージへ含まれます。
- LINE の利用数を取得する Lambda（`{env}-nandemo-oshirase-quota`）も同じ構成で、`service.name` は `nandemo-oshirase-quota` です。Collector の設定は `src/nandemo_oshirase_quota/collector.yaml`（送信の Lambda と同じ内容）です。
- 環境は、リソース属性 `deployment.environment.name`（と `deployment.environment`）の `dev`・`prod` で区別します。
- コールドスタートのときは、実行環境の初期化が `init <関数名>`（属性 `faas.coldstart=true`）という span になり、そのとき呼ばれた実行と同じトレースに入ります（Collector の `telemetryapi` receiver と `coldstart` processor）。また、初回の boto3 のクライアントの作成は `create_ssm_client`・`create_dynamodb_client` という span になります。
- Lambda の計装が付ける属性のうち、API Gateway のホスト（`net.host.name`）、AWS のアカウント ID（`cloud.account.id`）、関数の ARN（`cloud.resource_id`）は、Collector で消してから送ります（`attributes/redact`・`resource/redact`）。
- メトリクスは累積値（cumulative）で送ります。Lambda の実行環境が作り直されるとカウンタは 0 から数え直すので、Grafana では `increase()` や `rate()` で集計してください。
- ログは、アプリの `logging` のログを `opentelemetry-instrumentation-logging`（Python のレイヤー）が OTel のログにして送ります。ログにはそのときの span の `trace_id`・`span_id` が付くので、Grafana でトレースとログを行き来できます。CloudWatch Logs にも今までどおり出ます。
- Lambda の計装は、実行の終わりにトレースとメトリクスしか flush しません。ログは SDK がまとめて送るので、そのままでは応答を返したあとに実行環境が凍結され、次の呼び出しまで送られない（実行環境が止まると失われる）ことがあります。そのため、`lambda_handler` の最後でログを flush しています（`lambda_function.py` の `flush_logs`）。
- ログの本文は、ARN の中の AWS のアカウント ID を Collector で `***` に置き換えてから送ります（`transform/redact_log_body`。例: スケジュールからの呼び出しのログの `schedule_arn`）。CloudWatch Logs には元のまま出ます。ほかはそのまま送るので、送り先の LINE のユーザー ID（`user_id=...`・webhook の `userId=...`）も含まれます。

### OTel の Python のレイヤー

OTel の SDK・計装と、ハンドラーのラッパーを入れたレイヤーを自前で作っています（`tf/modules/otel_layers/main.tf` の `aws_lambda_layer_version.otel_python`）。コミュニティの Python計装レイヤーは使いません。

コミュニティの Python計装レイヤーは python3.14 で作られていて、入っている `.pyc` は python3.14 用（`cpython-314`）だけです。python3.13 の Lambda ではそれを使えず、`/opt` には書き込めないので、コールドスタートのたびにレイヤーのモジュール（約290個）をすべてコンパイルし直していました。自前のレイヤーには python3.13 用の `.pyc` を入れているので、コンパイルせずに読み込めます（手元で測ると、ラッパーの起動にかかる時間がおよそ半分になりました）。

- zip は `scripts/build-otel-python-layer.py` で作ります（CI の terraform-plan と CD で、Terraform の前に `uv run --no-project --python 3.13` で実行します）。`.pyc` はそれを作った Python のマイナーバージョンでしか使えないので、Lambda のランタイムと同じ python3.13 で実行します。
- 入れるパッケージは、`uv.lock` のアプリの依存（`pyproject.toml` の `dependencies` とその依存）です。Lambda のランタイムにある boto3・botocore・urllib3 などは入れません。計装を足すときは、`pyproject.toml` の `dependencies` に足すだけで、レイヤーにも入ります。
- 入れる wheel は、Lambda（x86_64、python3.13）用のものです（ビルドする環境の Python のものではありません）。
- `.pyc` は、ソースのハッシュで検証する形（unchecked-hash）で、`/opt/python` のパスで作ります。作った日時やビルドしたディレクトリが入らないので、同じ `uv.lock` なら zip のハッシュは変わらず、レイヤーは作り直されません。
- ハンドラーのラッパー（`/opt/otel-handler` など）は、コミュニティの Python計装レイヤーのものを `layers/otel-python` に持ってきて、そのまま入れています（`layers/otel-python/README.md` を参照）。
- `pyproject.toml` の OTel の依存は、コミュニティの Python計装レイヤー（タグの `requirements.txt`・`nodeps-requirements.txt`）と同じバージョンに `==` で固定しています。Dependabot では OTel のパッケージを上げません（`.github/dependabot.yml` の `ignore`）。
- レイヤーの ARN（自前の Python のレイヤーと、コミュニティの Collector レイヤー）は `tf/modules/otel_layers` にまとめ、重ねる順番もそこで決めています。Lambda のモジュールは、その output の `layer_arns` をそのまま `layers` に渡します。
- コミュニティのレイヤーの新しいバージョンは、`.github/workflows/update-otel-lambda-layers.yml` が見つけて、`tf/modules/otel_layers/main.tf` の Collector レイヤーの ARN と `pyproject.toml`・`uv.lock` の OTel の依存（Python計装レイヤーのバージョン）を一緒に上げる PR を develop に作ります。Python のレイヤーは、OTel の依存が上がれば次のデプロイで作り直されます。そのときは、`layers/otel-python` のラッパーが同じタグのものから変わっていないかも確認してください。opentelemetry-lambda のリリースは feed-release-invoke-workflow の `repository_dispatch`（`otel-lambda-release`）で知り、取りこぼしに備えて週1回の `schedule` でも確認します。

### Grafana Cloud の認証情報

Grafana Cloud に送るための Authorization ヘッダーの値（`Basic <base64(スタックの ID:トークン)>`）は、環境ごとに SSM Parameter Store の SecureString（AWS管理キー `aws/ssm`）に置かれている前提です。パラメータはこのリポジトリの外で作成・管理します。

トークン（Access Policy）には、`traces:write`・`metrics:write`・`logs:write` の権限が要ります。`logs:write` が無いと、ログの送信だけが 401/403 で失敗します。

| 環境 | パラメータ |
|---|---|
| dev | `/app/grafana/dev/otlp_auth` |
| prod | `/app/grafana/prod/otlp_auth` |

Collectorレイヤーは SSM Parameter Store を読めないため、Terraform がこのパラメータを読み、Lambda の環境変数 `GRAFANA_CLOUD_OTLP_AUTH` に渡します。そのため、LINE の認証情報と違い、**この値は Terraform の state と Lambda の環境変数に残ります**。送信先（`GRAFANA_CLOUD_OTLP_ENDPOINT`）は秘密ではないので、Terraform の変数 `grafana_otlp_endpoint` に直接書いています。値は、Grafana Cloud のスタックの OTLP の URL に `/otlp` を付けたものです。

パラメータの値が変わったとき（トークンを作り直したときなど）は、このリポジトリでもう一度 apply すると、Lambda の環境変数が新しい値に変わります。

## CLI の実行に必要な IAM 権限

CLI を実行する AWS 認証情報には、次の権限が必要です。

| 権限 | 対象 |
|---|---|
| `scheduler:CreateSchedule` / `GetSchedule` / `UpdateSchedule` / `DeleteSchedule` | `arn:aws:scheduler:*:*:schedule/{env}-nandemo-oshirase-reminders/*` |
| `scheduler:ListSchedules` | `*` |
| `iam:PassRole` | `{env}-nandemo-oshirase-scheduler-role` |
| `sts:GetCallerIdentity` | `*` |
| `lambda:InvokeFunction`（`send` を使う場合のみ） | `{env}-nandemo-oshirase-function` |
