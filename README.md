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
