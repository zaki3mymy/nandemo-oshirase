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

### LINE の利用数を取得する Lambda（lambda-quota）

LINE の当月の利用数と上限を取得する Lambda（`src/nandemo_oshirase_quota`）は、`lambda-quota` コンテナ（`http://localhost:9001`）で動きます。送信の Lambda と同じイメージで、ハンドラーだけを変えています。stub は上限に `{"type": "limited", "value": 200}`、利用数に `{"totalUsage": 42}` を返します。

```bash
curl -X POST "http://localhost:9001/2015-03-31/functions/function/invocations" -d '{}'
# => {"totalUsage": 42, "limit": 200}
```

メトリクス `line_quota_consumption`・`line_quota_limit` が Prometheus に、`get_message_quota`・`get_message_consumption` の span が Jaeger（サービス `nandemo-oshirase-quota`）に届きます。

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

## ミューテーションテスト

[mutmut](https://github.com/boxed/mutmut) で単体テストの検証の強さを確認できます。ソースを少し書き換えたもの（ミュータント）ごとに `tests/unit/` を流し、テストが落ちなかったもの（survived）が「実行はしているが結果を検証できていない」箇所です。設定は `pyproject.toml` の `[tool.mutmut]` にあります。

```bash
uv run mutmut run              # 実行（作業用に mutants/ が作られる）
uv run mutmut results          # survived の一覧
uv run mutmut show <名前>       # ミュータントの差分を表示
uv run mutmut browse           # TUI で確認
```

mutmut は同じプロセスで pytest を何度も実行するため、hypothesis のプロファイル `mutmut`（`tests/unit/conftest.py`）を使い、カバレッジ計測も切っています。ログの文言はテストで固定しないので、`logger.` を含む行はミュータントを作りません。

### 週次の issue

`.github/workflows/mutation-test.yml` が毎週月曜 7:53（日本時間）に mutmut を実行し、`scripts/mutation_report.py` で survived を次のように分類します。分類は差分のトークンを比べるだけの決定論的なルールです。

| 区分 | 内容 |
|---|---|
| 高 | 演算子・条件・制御（`and`/`or`、`+`/`-`、比較、`break`/`continue`）、数値・真偽値の変更 |
| 中 | 値の `None` への置き換え、引数・キーワードの削除 |
| 低 | 文字列リテラルだけの変更（例外メッセージ・dict のキー・既定値など） |
| 対象外 | `help`・`metavar`・span 名など、振る舞いに関わらない文字列の変更 |

- 高・中が 1 件以上あれば、開いている issue の本文を最新の結果で上書きします（無ければ作ります）。
- 高・中が 0 件になったら、その issue にコメントしてクローズします。その後また見つかったら、新しい issue を作ります。
- PR をマージした直後に確認したいときは、Actions の画面から手動で実行できます（`workflow_dispatch`）。

ローカルでレポートを作るには、`uv run mutmut run` のあとに `uv run python scripts/mutation_report.py --out report.md` を実行します。

### issue の候補の直し方

テストファイルの単位（例: Lambda のルーティングと送信、CLI の引数）でまとめて 1 つの PR にします。候補ごとに、次のどちらかで解消します。

- **テストを足す**: ミュータントの差分を見て、その変更で結果が変わることを確かめるテストを書きます。ログの文言は固定せず、ログに出す値（`record.args`）を確かめるのは構いません。
- **等価なミュータントとして除く**: 変更しても振る舞いが変わらない（例: `data` を渡した `urllib.request.Request` の `method="POST"`）なら、その引数の行に `# pragma: no mutate` を付けます。理由はすぐ上の行にコメントで書きます（pragma の後ろに続けると、`block` などの指定と紛らわしくなるため）。pragma は付けた行の変更だけを止めるので、ほかの引数の変更も止めないよう、引数を 1 行ずつに分けてから付けます。

```python
request = urllib.request.Request(
    url,
    data=body,
    headers=headers,
    # data を渡すと urllib は POST で送るので、method を変えても振る舞いは同じ（明示のため）
    method="POST",  # pragma: no mutate
)
```

直ったかどうかは、全件を流し直さず、名前（ワイルドカード可）で絞って確認できます。名前を指定すると、前回の結果があっても実行し直します。

```bash
uv run mutmut run "nandemo_oshirase.lambda_function.x_route__mutmut_*"   # 関数の単位
uv run mutmut run "nandemo_oshirase.lambda_function.*"                    # モジュールの単位
uv run mutmut results                                                     # survived が消えたか
```

マージ後の週次の実行（または手動実行）で issue から消え、高・中が 0 件になれば issue は自動でクローズされます。
