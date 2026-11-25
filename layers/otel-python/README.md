# OTel の Python レイヤーのラッパー

`scripts/build-otel-python-layer.py` が作る Lambda レイヤーに入れる、ハンドラーのラッパーです。
[opentelemetry-lambda](https://github.com/open-telemetry/opentelemetry-lambda) の
`python/src/otel/otel_sdk`（タグ `layer-python/0.22.0`）から、変えずに持ってきています（Apache License 2.0。`LICENSE` を参照）。

| ファイル | レイヤーでの場所 | 役目 |
|---|---|---|
| `otel-handler` | `/opt/otel-handler` | `AWS_LAMBDA_EXEC_WRAPPER` に指定する。`otel-instrument` を呼ぶだけ |
| `otel-instrument` | `/opt/otel-instrument` | OTel の環境変数の既定値を入れ、`opentelemetry-instrument` でランタイムを起動する |
| `otel_wrapper.py` | `/opt/python/otel_wrapper.py` | 元のハンドラー（`ORIG_HANDLER`）を読み込む |

コミュニティのレイヤーを新しいバージョンに上げたときは、同じタグのこれらのファイルと見比べ、変わっていれば持ってき直してください。
