# 開発

PR のタイトルの付け方とリリースの流れは [release.md](release.md) を見てください。

## 開発環境

開発に使うツールは [flake.nix](../flake.nix) で管理する。

| ツール | 用途 |
| --- | --- |
| uv | Python と依存関係の管理 |
| pre-commit | コミット前のチェック。開発環境に入ると、フックが自動で入る（flake.nix の `shellHook`） |
| nodejs | `scripts/build-docs.sh` の `npx`（API のドキュメントのビルド） |

次のものは flake に入れていないので、別に入れる。

- Python：uv が `.python-version` を見て入れる（CI の `setup-uv` と同じ）。ruff などの Python のツールは uv.lock で管理し、`uv run` で使う
- terraform：unfree で cache.nixos.org にビルド済みのものがなく、flake.lock を更新するたびにソースからのビルド（数分）がかかるため。CI では `hashicorp/setup-terraform` で入れる
- podman・podman-compose：コンテナでの動作確認に使う。コンテナのランタイムなので OS 側で用意する

[direnv](https://direnv.net/) を使うと、このディレクトリに入ったときに自動でツールが PATH に入る（[.envrc](../.envrc)）。direnv を使わないときは `nix develop` を実行する。

```shell
direnv allow   # または nix develop
```

- ツールのバージョンは、flake.lock の nixpkgs のコミット（`rev`）で決まる。nixpkgs のコミットを進めると、すべてのツールがまとめて新しくなる。
  - 更新は Dependabot が週に1回 PR を作る。手で上げるときは `nix flake update` を実行する。
  - 実際のバージョンは `nix develop -c uv --version` や `nix eval --inputs-from . --raw nixpkgs#uv.version` で確かめられる。
- uv のバージョンは `pyproject.toml` の `[tool.uv] required-version` の範囲のものを使う（CI も同じ範囲の uv を使う）。nixpkgs を進めて uv が範囲から外れたら、`required-version` と CI の uv を合わせて上げる。

## セットアップ

```bash
# 依存関係のインストール
uv sync --dev

# テスト実行
uv run pytest
```

pre-commit のフックは、開発環境に入ったとき（`direnv allow` のあと、または `nix develop`）に自動で入ります。

## ローカル環境変数の設定

ローカル実行に必要な秘匿情報は `.env.local` で管理します（git 管理対象外）。

```bash
cp .env.example .env.local
# .env.local を編集して値を設定
```

## コンテナでの動作確認

`podman-compose` を使い、lambdaコンテナ（AWS Lambda Runtime Interface Emulator）と、LINE APIのスタブ（`mockoon/cli`）、OTelのテレメトリ収集・可視化スタック（otel-collector / Jaeger / Prometheus / Loki / Grafana）を起動して疎通確認できます。lambdaコンテナは `LINE_API_BASE_URL=http://stub:3000` を参照し、本番のLINE APIではなくstubにリクエストを送ります。

[再送](../README.md#再送冪等性)の再送キーは DynamoDB Local（`dynamodb`、`http://localhost:8000`）に保存します。テーブルは `dynamodb-init` が起動時に作ります（データはメモリにだけあり、止めると消えます）。stub の push API は、ボディに `__error__` が含まれると `500` を、`__already_sent__` が含まれると `409`（送信済みの再送キー）を返します。

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

## OTelメトリクス・トレース・ログの確認

lambdaコンテナは `AWS_LAMBDA_EXEC_WRAPPER` により `opentelemetry-instrument` 経由で起動され、OTLP/HTTPでotel-collectorにテレメトリを送信します。上記のリクエストを送った後、以下のUIで確認できます。

| ツール | URL | 用途 |
|--------|-----|------|
| Jaeger | http://localhost:16686 | トレースの可視化 |
| Grafana | http://localhost:3000 | メトリクスダッシュボード、ログ（Prometheus・Jaeger・Lokiのデータソースは自動プロビジョニング済み、初回ログインは `admin` / `admin`） |
| Prometheus | http://localhost:9090 | メトリクスの生データ確認 |
| Loki | http://localhost:3100 | ログの保存先（Grafana の Explore でデータソース Loki を選び、`{service_name="nandemo-oshirase"}` で確認。ログの `trace_id` から Jaeger のトレースを開ける） |

ローカル用のCollector/Prometheus設定は `config/` ディレクトリにまとめています（`config/otel-collector-config.yaml`、`config/prometheus.yml`、`config/grafana/`）。

## 結合テスト

`tests/integration/` には、手動計装したトレース・メトリクスと、ログが実際にJaeger・Prometheus・Lokiまで届いていることを確認する結合テストがあります。`uv run pytest` の対象には含まれず、`podman-compose up -d` でスタック一式を起動した状態で明示的に実行します。

```bash
podman-compose up -d
uv run pytest tests/integration/
```
