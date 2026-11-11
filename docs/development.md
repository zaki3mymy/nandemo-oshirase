# 開発

PR のタイトルの付け方とリリースの流れは [release.md](release.md) を見てください。

```bash
# 依存関係のインストール
uv sync --dev

# テスト実行
uv run pytest

# pre-commitフックのインストール
uv run pre-commit install
```

## ローカル環境変数の設定

ローカル実行に必要な秘匿情報は `.env.local` で管理します（git 管理対象外）。

```bash
cp .env.example .env.local
# .env.local を編集して値を設定
```

## コンテナでの動作確認

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

## OTelメトリクス・トレースの確認

lambdaコンテナは `AWS_LAMBDA_EXEC_WRAPPER` により `opentelemetry-instrument` 経由で起動され、OTLP/HTTPでotel-collectorにテレメトリを送信します。上記のリクエストを送った後、以下のUIで確認できます。

| ツール | URL | 用途 |
|--------|-----|------|
| Jaeger | http://localhost:16686 | トレースの可視化 |
| Grafana | http://localhost:3000 | メトリクスダッシュボード（Prometheusデータソースは自動プロビジョニング済み、初回ログインは `admin` / `admin`） |
| Prometheus | http://localhost:9090 | メトリクスの生データ確認 |

ローカル用のCollector/Prometheus設定は `config/` ディレクトリにまとめています（`config/otel-collector-config.yaml`、`config/prometheus.yml`、`config/grafana/`）。

## 結合テスト

`tests/integration/` には、手動計装したトレース・メトリクスが実際にJaeger・Prometheusまで届いていることを確認する結合テストがあります。`uv run pytest` の対象には含まれず、`podman-compose up -d` でスタック一式を起動した状態で明示的に実行します。

```bash
podman-compose up -d
uv run pytest tests/integration/
```
