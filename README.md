# なんでもお知らせくん

任意のメッセージをLINEに送信するシンプルな通知API。

## デプロイ

mainブランチへのマージ時にGitHub Actionsで自動デプロイされます。

### GitHub Secrets

以下のシークレットを設定してください:

| Secret | 説明 |
|--------|------|
| `AWS_ROLE_ARN` | OIDC認証用のIAMロールARN |
| `TERRAFORM_STATE_BUCKET` | Terraform state用S3バケット名 |
| `LINE_CHANNEL_TOKEN` | LINE Messaging API Channel Access Token |
| `LINE_USER_ID` | 通知先のLINE User ID |

### 本番環境のOTelテレメトリ

本番Lambdaには OTel の Python計装レイヤーと Collectorレイヤーをアタッチしており、認証はLambda実行ロールのIAM権限（`AWSXRayDaemonWriteAccess` / `CloudWatchAgentServerPolicy`）で行います。追加のシークレット設定は不要です。

トレース・メトリクスの転送先とCollectorの設定は `src/nandemo_oshirase/collector.yaml` にまとめており、デプロイ時にLambdaのデプロイパッケージへ含まれます。

| テレメトリ | バックエンド | 確認方法 |
|---|---|---|
| トレース | AWS X-Ray | X-Ray コンソール / CloudWatch ServiceLens |
| メトリクス | Amazon CloudWatch (EMF) | CloudWatch メトリクス（namespace: `NandemoOshirase`） |

## 使い方

```bash
curl -X POST <ENDPOINT> \
  -H "x-api-key: <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!"}'
```

複数メッセージを送信する場合:

```bash
curl -X POST <ENDPOINT> \
  -H "x-api-key: <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"messages": ["1つ目", "2つ目", "3つ目"]}'
```

## 開発

```bash
# 依存関係のインストール
uv sync --dev

# テスト実行
uv run pytest

# pre-commitフックのインストール
uv run pre-commit install
```

### ローカル環境変数の設定

ローカル実行に必要な秘匿情報は `.env.local` で管理します（git 管理対象外）。

```bash
cp .env.example .env.local
# .env.local を編集して値を設定
```

### コンテナでの動作確認

`podman-compose` を使い、lambdaコンテナ（AWS Lambda Runtime Interface Emulator）と、LINE APIのスタブ（`mockoon/cli`）、OTelのテレメトリ収集・可視化スタック（otel-collector / Jaeger / Prometheus / Grafana）を起動して疎通確認できます。lambdaコンテナは `LINE_API_BASE_URL=http://stub:3000` を参照し、本番のLINE APIではなくstubにリクエストを送ります。

```bash
podman-compose up --build
```

起動後、Lambda RIE のエンドポイント（`http://localhost:9000/2015-03-31/functions/function/invocations`）経由で各エンドポイントを呼び出せます。

```bash
# POST /notify
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -d '{"httpMethod":"POST","path":"/notify","body":"{\"message\":\"Hello!\"}"}'

# POST /webhook
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -d '{"httpMethod":"POST","path":"/webhook","body":"{\"events\":[]}"}'

# GET /docs
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -d '{"httpMethod":"GET","path":"/docs"}'
```

### OTelメトリクス・トレースの確認

lambdaコンテナは `AWS_LAMBDA_EXEC_WRAPPER` により `opentelemetry-instrument` 経由で起動され、OTLP/HTTPでotel-collectorにテレメトリを送信します。上記のリクエストを送った後、以下のUIで確認できます。

| ツール | URL | 用途 |
|--------|-----|------|
| Jaeger | http://localhost:16686 | トレースの可視化 |
| Grafana | http://localhost:3000 | メトリクスダッシュボード（Prometheusデータソースは自動プロビジョニング済み、初回ログインは `admin` / `admin`） |
| Prometheus | http://localhost:9090 | メトリクスの生データ確認 |

ローカル用のCollector/Prometheus設定は `config/` ディレクトリにまとめています（`config/otel-collector-config.yaml`、`config/prometheus.yml`、`config/grafana/`）。

### 結合テスト

`tests/integration/` には、手動計装したトレース・メトリクスが実際にJaeger・Prometheusまで届いていることを確認する結合テストがあります。`uv run pytest` の対象には含まれず、`podman-compose up -d` でスタック一式を起動した状態で明示的に実行します。

```bash
podman-compose up -d
uv run pytest tests/integration/
```
