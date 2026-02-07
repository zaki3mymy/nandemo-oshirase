# なんでもお知らせくん

任意のメッセージをLINEに送信するシンプルな通知API。

## デプロイ

```bash
cd tf
cp example.tfvars terraform.tfvars
# terraform.tfvars を編集（LINE_CHANNEL_TOKEN, LINE_USER_ID を設定）
terraform init
terraform apply
```

デプロイ後、エンドポイントURLとAPIキーが出力されます。

```bash
terraform output api_endpoint
terraform output -raw api_key
```

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
