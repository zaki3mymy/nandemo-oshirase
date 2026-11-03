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

## 定時お知らせ（`oshirase` CLI）

「毎週月曜21時に『明日は燃えるゴミです』」のような定時のお知らせを、EventBridge Scheduler から Lambda を直接 invoke して送ります。

送信時刻とメッセージは AWS 上の EventBridge Scheduler にだけ保存され、このリポジトリや Terraform state には残りません。Terraform が管理するのはスケジュールグループ（`{env}-nandemo-oshirase-reminders`）と Scheduler 用 IAM ロールだけです。

```bash
# 追加
uv run oshirase add gomi-moeru --weekly mon --at 21:00 -m "明日は燃えるゴミです"
uv run oshirase add shigen --weekly wed --nth 2 --at 21:00 -m "明日は資源ごみです"  # 毎月第2水曜
uv run oshirase add morning --daily --at 7:00 -m "おはよう" -m "傘を忘れずに"       # 複数メッセージ
uv run oshirase add monthly --cron "0 8 1 * ? *" -m "月初の作業"                   # cron式を直接指定

# 一覧・詳細
uv run oshirase list
uv run oshirase show gomi-moeru

# 変更（指定した項目だけ変わる）
uv run oshirase update gomi-moeru --at 20:30
uv run oshirase update gomi-moeru -m "明日は燃えるゴミの日です"

# 一時停止・再開・削除
uv run oshirase disable gomi-moeru
uv run oshirase enable gomi-moeru
uv run oshirase delete gomi-moeru

# 今すぐ送って動作確認
uv run oshirase send gomi-moeru
```

- 曜日は `mon,thu` のほか `月,木` でも指定できます。
- 名前に使えるのは英数字と `- _ .` だけです（EventBridge Scheduler の制約）。
- 「第1・第3水曜」のように1つの式で表せないものは、`shigen-1` と `shigen-3` のように2件に分けて登録します。
- 時刻はタイムゾーン `Asia/Tokyo` で解釈します。変えたい場合は `--timezone` を指定します。
- 共通オプション（`--env dev`、`--profile`、`--region`）はサブコマンドより前に書きます。例：`uv run oshirase --env dev list`。`OSHIRASE_ENV` 環境変数で既定の環境を変えることもできます。

### CLI の実行に必要な IAM 権限

CLI を実行する AWS 認証情報には、次の権限が必要です。

| 権限 | 対象 |
|---|---|
| `scheduler:CreateSchedule` / `GetSchedule` / `UpdateSchedule` / `DeleteSchedule` | `arn:aws:scheduler:*:*:schedule/{env}-nandemo-oshirase-reminders/*` |
| `scheduler:ListSchedules` | `*` |
| `iam:PassRole` | `{env}-nandemo-oshirase-scheduler-role` |
| `sts:GetCallerIdentity` | `*` |
| `lambda:InvokeFunction`（`send` を使う場合のみ） | `{env}-nandemo-oshirase-function` |

### 仕組み

- スケジュールは Lambda に `{"source": "nandemo-oshirase.scheduler", "messages": [...]}` を非同期で invoke します。
- 送信に失敗すると Lambda はエラーになり、1回だけリトライします。1時間以上遅れたお知らせは送りません。

## 開発

```bash
# 依存関係のインストール
uv sync --dev

# テスト実行
uv run pytest

# pre-commitフックのインストール
uv run pre-commit install
```

Nix を使う場合は `nix develop` で Python・uv・Node.js・Terraform（CI と同じ 1.9 系）が揃います。

Claude Code のクラウドセッションでは、SessionStart フック（`.claude/hooks/session-start.sh`）が同じツールを Nix で用意し、`uv sync --dev` と `terraform init -backend=false` まで済ませます。nixpkgs は GitHub ではなく `channels.nixos.org` から取得しています（クラウドセッションの GitHub プロキシは、セッションに付いていないリポジトリの取得を拒否するため）。

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
