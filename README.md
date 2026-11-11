# なんでもお知らせくん

任意のメッセージをLINEに送信するシンプルな通知API。

- `POST /notify` で、任意のメッセージを LINE に送ります。
- `oshirase` CLI で、「毎週月曜21時」のような定時のお知らせを登録できます。
- `GET /docs` で、API のドキュメントを表示します。

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

送信せずに動作を確認する場合（dry run）:

```bash
curl -X POST <ENDPOINT> \
  -H "x-api-key: <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!", "dry_run": true}'
```

`dry_run` が `true`（真偽値）のときは、LINE の認証情報の読み込み、メッセージの検証、バッチへの分割までを行い、LINE には送信しません。そのうえで、LINE の [validate API](https://developers.line.biz/en/reference/messaging-api/#validate-message-objects-of-push-message)（`POST /v2/bot/message/validate/push`）で、チャネルアクセストークンとメッセージの形式を確認します。成功すると `200` で `{"message": "Dry run: would send 1 message(s) in 1 batch(es)"}` を返します。

- トークンが無効なときなど、LINE の validate API がエラーを返したときは、そのステータスコードと `{"error": "..."}` を返します。
- 送り先（`LINE_USER_ID`）が正しいかは確認できません。

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

CLI を実行する AWS 認証情報に必要な IAM 権限は、[docs/deployment.md](docs/deployment.md#cli-の実行に必要な-iam-権限) にまとめています。

### 仕組み

- スケジュールは Lambda に `{"source": "nandemo-oshirase.scheduler", "messages": [...]}` を非同期で invoke します。
- 送信に失敗すると Lambda はエラーになり、1回だけリトライします。1時間以上遅れたお知らせは送りません。

## ドキュメント

- [デプロイ](docs/deployment.md)：デプロイの前提、GitHub Secrets、LINE の認証情報、本番のテレメトリ、CLI の IAM 権限
- [リリース](docs/release.md)：タグと GitHub リリース、PR タイトルの規約、バージョンの決め方
- [開発](docs/development.md)：開発環境の準備、コンテナでの動作確認、結合テスト
