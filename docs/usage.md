# 使い方

## POST /notify

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

API の詳細は `GET /docs`（[openapi.yaml](../openapi.yaml)）を見てください。

### dry run

送信せずに動作を確認する場合:

```bash
curl -X POST <ENDPOINT> \
  -H "x-api-key: <API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!", "dry_run": true}'
```

`dry_run` が `true`（真偽値）のときは、LINE の認証情報の読み込み、メッセージの検証、バッチへの分割までを行い、LINE には送信しません。そのうえで、LINE の [validate API](https://developers.line.biz/en/reference/messaging-api/#validate-message-objects-of-push-message)（`POST /v2/bot/message/validate/push`）で、チャネルアクセストークンとメッセージの形式を確認します。成功すると `200` で `{"message": "Dry run: would send 1 message(s) in 1 batch(es)"}` を返します。

- トークンが無効なときなど、LINE の validate API がエラーを返したときは、そのステータスコードと `{"error": "..."}` を返します。
- 送り先（`LINE_USER_ID`）が正しいかは確認できません。
- validate API は送信ではないので、LINE の月の送信数（無料プランは 200 通）を使いません。CD の動作確認は、dev・本番とも dry run で行います。

### 再送

同じリクエストを **15分以内** に再送したときは、送信済みのメッセージを LINE に送らず、最初のリクエストと同じレスポンスを返します。タイムアウトなどで結果が分からないときは、15分以内であれば安心して再送できます。

- 同じリクエストとは、`messages`（または `message`）の内容と順番がすべて同じリクエストです。リクエスト元は区別しないので、別のシステムから同じ内容が届いたときも1回だけ送ります。
- 6件以上のメッセージは5件ずつに分けて送ります。途中で失敗したリクエストを再送すると、失敗した分から送り直します。
- 15分を過ぎた再送は、別のメッセージとして送ります。意図して同じメッセージを2回送りたいときは、15分以上あけてください。
- dry run は再送の判定に含めません。

仕組みは [アーキテクチャ](architecture.md#再送冪等性) を見てください。

## 定時お知らせ（`oshirase` CLI）

「毎週月曜21時に『明日は燃えるゴミです』」のような定時のお知らせを登録します。仕組みは [アーキテクチャ](architecture.md#定時お知らせ) を見てください。

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

# dry run（時刻になっても LINE に送信せず、validate API での確認だけにする）
uv run oshirase --env dev add check --daily --at 9:00 -m "動作確認" --dry-run
uv run oshirase --env dev update check --no-dry-run  # 解除（--dry-run で再び dry run）
```

- 曜日は `mon,thu` のほか `月,木` でも指定できます。
- 名前に使えるのは英数字と `- _ .` だけです（EventBridge Scheduler の制約）。
- 「第1・第3水曜」のように1つの式で表せないものは、`shigen-1` と `shigen-3` のように2件に分けて登録します。
- 時刻はタイムゾーン `Asia/Tokyo` で解釈します。変えたい場合は `--timezone` を指定します。
- `--dry-run` のお知らせは、`list` と `show` で `[dry run]` と表示されます。`send` でも送信しません。dry run は LINE の月の送信数を使わないので、CD の動作確認はこれで行います。
- 共通オプション（`--env dev`、`--profile`、`--region`）はサブコマンドより前に書きます。例：`uv run oshirase --env dev list`。`OSHIRASE_ENV` 環境変数で既定の環境を変えることもできます。

CLI を実行する AWS 認証情報に必要な IAM 権限は、[デプロイ](deployment.md#cli-の実行に必要な-iam-権限) にまとめています。
