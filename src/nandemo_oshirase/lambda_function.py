"""Lambda function for LINE notification service."""

import base64
import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, NamedTuple, NotRequired, TypedDict, TypeIs

from opentelemetry import metrics, trace

logger = logging.getLogger(__name__)
# 不正な LOG_LEVEL のときは INFO にする
_log_level = logging.getLevelNamesMapping().get(
    os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO
)
logger.setLevel(_log_level)

_tracer = trace.get_tracer("nandemo_oshirase")
_meter = metrics.get_meter("nandemo_oshirase")

_notification_counter = _meter.create_counter(
    "line.notifications.sent",
    unit="1",
    description="Number of LINE notifications sent",
)
_batch_count_histogram = _meter.create_histogram(
    "line.messages.batch_count",
    unit="1",
    description="Number of batches per request",
)


class LambdaEvent(TypedDict):
    body: NotRequired[str | None]
    isBase64Encoded: NotRequired[bool]
    httpMethod: NotRequired[str]
    path: NotRequired[str]


class ScheduledEvent(TypedDict):
    """Event sent by EventBridge Scheduler via direct Lambda invocation."""

    source: str
    messages: list[str]
    schedule_arn: NotRequired[str]


class LambdaResponse(TypedDict):
    statusCode: int
    body: str
    headers: NotRequired[dict[str, str]]


class LineMessage(TypedDict):
    type: str
    text: str


SCHEDULER_EVENT_SOURCE = "nandemo-oshirase.scheduler"


class ScheduledNotificationError(Exception):
    """Raised when a scheduled notification cannot be delivered.

    Scheduled invocations are asynchronous, so the return value is discarded.
    Raising makes the failure visible to Lambda (retry / Errors metric).
    """


@dataclass(frozen=True, slots=True)
class NotifyRequest:
    """Parsed body of POST /notify."""

    messages: list[str]
    # True のときは LINE に送信しない（デプロイ後の動作確認用）
    dry_run: bool = False


def is_dry_run(data: dict[str, Any]) -> bool:
    """Return True only if ``dry_run`` is the JSON boolean ``true``.

    文字列の "true" などは dry run として扱わない。
    スケジュール実行のイベントでも同じ判定を使えるように関数にしている。
    """
    return data.get("dry_run") is True


class WebhookSource(TypedDict):
    type: str
    userId: NotRequired[str]
    groupId: NotRequired[str]
    roomId: NotRequired[str]


class WebhookEvent(TypedDict):
    source: NotRequired[WebhookSource]


class WebhookBody(TypedDict):
    events: NotRequired[list[WebhookEvent]]


def parse_request(event: LambdaEvent) -> NotifyRequest:
    """Parse Lambda event and extract messages and the dry_run flag."""
    body = event.get("body")
    if not body:
        raise ValueError("Invalid JSON: empty body")

    if event.get("isBase64Encoded"):
        logger.debug("Decoding Base64-encoded body")
        body = base64.b64decode(body).decode("utf-8")

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e

    if "message" in data:
        logger.info("Parsed single message from request")
        messages = [data["message"]]
    elif "messages" in data:
        logger.info("Parsed %d message(s) from request", len(data["messages"]))
        messages = data["messages"]
    else:
        raise ValueError("No message or messages key found")

    return NotifyRequest(messages=messages, dry_run=is_dry_run(data))


def validate_messages(messages: list[str]) -> list[str]:
    """Validate and filter messages."""
    validated = [msg for msg in messages if msg.strip()]
    skipped = len(messages) - len(validated)
    if skipped:
        logger.warning("Skipped %d empty message(s)", skipped)
    return validated


def format_line_messages(messages: list[str]) -> list[LineMessage]:
    """Format messages for LINE Messaging API."""
    return [{"type": "text", "text": msg} for msg in messages]


def split_into_batches(messages: list[LineMessage], batch_size: int = 5) -> list[list[LineMessage]]:
    """Split messages into batches."""
    if not messages:
        return []
    return [messages[i : i + batch_size] for i in range(0, len(messages), batch_size)]


def _post_line_api(
    path: str,
    payload: dict[str, Any],
    channel_token: str,
    extra_headers: dict[str, str] | None = None,
) -> LambdaResponse:
    """POST a JSON payload to the LINE Messaging API.

    LINE API のエラーは statusCode と {"error": reason} に変換して返す（例外にはしない）。
    """
    base_url = os.environ.get("LINE_API_BASE_URL", "https://api.line.me")
    url = f"{base_url}{path}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel_token}",
        **(extra_headers or {}),
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(request) as response:
            status = response.status
            response_body = response.read().decode("utf-8")
            logger.info("LINE API %s responded with status %d", path, status)
            return {"statusCode": status, "body": response_body}
    except urllib.error.HTTPError as e:
        logger.error("LINE API %s error: status=%d reason=%s", path, e.code, e.reason)
        return {"statusCode": e.code, "body": json.dumps({"error": e.reason})}
    except urllib.error.URLError as e:
        logger.error("LINE API %s connection error: %s", path, e.reason)
        return {"statusCode": 502, "body": json.dumps({"error": str(e.reason)})}


@_tracer.start_as_current_span("push_messages")
def push_messages(
    messages: list[LineMessage], channel_token: str, user_id: str, retry_key: str | None = None
) -> LambdaResponse:
    """Send messages to LINE Messaging API.

    retry_key を渡すと X-Line-Retry-Key ヘッダーに付ける。同じ再送キーのリクエストを
    LINE がすでに受け付けていたときは、LINE は送信せずに 409 を返す。
    """
    # このバッチ（最大 batch_size 件）に含まれるメッセージ数。リクエスト全体の総数ではない。
    trace.get_current_span().set_attribute("line.batch_message_count", len(messages))

    logger.info("Sending %d message(s) to LINE API (user_id=%s)", len(messages), user_id)
    result = _post_line_api(
        "/v2/bot/message/push",
        {"to": user_id, "messages": messages},
        channel_token,
        {"X-Line-Retry-Key": retry_key} if retry_key else None,
    )
    # エラーのときは _post_line_api が 4xx / 5xx を返す
    if 200 <= result["statusCode"] < 300:
        status = "success"
    elif result["statusCode"] == 409 and retry_key:
        status = "duplicate"
    else:
        status = "error"
    _notification_counter.add(len(messages), {"status": status})
    return result


@_tracer.start_as_current_span("validate_push_messages")
def validate_push_messages(messages: list[LineMessage], channel_token: str) -> LambdaResponse:
    """Validate message objects with the LINE validate API, without sending them.

    チャネルアクセストークンとメッセージの形式を確認できる。送り先（user_id）は確認できない。
    """
    trace.get_current_span().set_attribute("line.batch_message_count", len(messages))

    logger.info("Validating %d message(s) with LINE API", len(messages))
    return _post_line_api("/v2/bot/message/validate/push", {"messages": messages}, channel_token)


@_tracer.start_as_current_span("handle_webhook")
def handle_webhook(event: LambdaEvent) -> LambdaResponse:
    """Handle POST /webhook: log source IDs from LINE webhook events."""
    body = event.get("body")
    if not body:
        logger.warning("Webhook received empty body")
        return {"statusCode": 200, "body": json.dumps({"message": "ok"})}

    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")

    try:
        data: WebhookBody = json.loads(body)
    except json.JSONDecodeError as e:
        logger.warning("Webhook received invalid JSON: %s", e)
        return {"statusCode": 200, "body": json.dumps({"message": "ok"})}

    for webhook_event in data.get("events", []):
        source: WebhookSource = webhook_event.get("source", {"type": "unknown"})
        source_type = source.get("type")
        if source_type == "user":
            logger.info("Webhook source: type=user userId=%s", source.get("userId"))
        elif source_type == "group":
            logger.info(
                "Webhook source: type=group groupId=%s userId=%s",
                source.get("groupId"),
                source.get("userId"),
            )
        elif source_type == "room":
            logger.info(
                "Webhook source: type=room roomId=%s userId=%s",
                source.get("roomId"),
                source.get("userId"),
            )
        else:
            logger.info("Webhook source: type=%s source=%s", source_type, source)

    return {"statusCode": 200, "body": json.dumps({"message": "ok"})}


@_tracer.start_as_current_span("serve_docs")
def serve_docs() -> LambdaResponse:
    """Return Swagger UI HTML for GET /docs."""
    html_path = os.path.join(os.path.dirname(__file__), "docs.html")
    with _tracer.start_as_current_span("open_file"):
        with open(html_path) as f:
            html = f.read()
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html"},
        "body": html,
    }


class LineCredentials(NamedTuple):
    channel_token: str
    user_id: str


class MissingCredentialError(Exception):
    """Raised when a required LINE credential cannot be resolved."""


# SSM から読んだ値のキャッシュの有効期限。SSM の値を更新したとき、
# デプロイし直さなくてもこの時間が経てば新しい値に切り替わる。
CREDENTIALS_CACHE_TTL_SECONDS = 15 * 60

# (環境変数名, パラメータ名を持つ環境変数名)
_CREDENTIAL_SOURCES = {
    "channel_token": ("LINE_CHANNEL_TOKEN", "LINE_CHANNEL_TOKEN_PARAM"),
    "user_id": ("LINE_USER_ID", "LINE_USER_ID_PARAM"),
}

_ssm_client: Any = None
_ssm_cache: dict[str, tuple[str, float]] = {}


def _create_boto3_client(service: str) -> Any:
    """Create a boto3 client in its own span (boto3 is provided by the Lambda runtime).

    初回の import boto3 とクライアントの作成は、コールドスタートでは数秒かかることがある。
    それを呼び出し元の span（SSM や DynamoDB の処理）の時間と区別できるよう、別の span にする。
    クライアントはキャッシュするので、この span はコールドスタートのあとの最初の呼び出しでだけ出る。
    """
    with _tracer.start_as_current_span(f"create_{service}_client"):
        import boto3

        return boto3.client(service)


def _get_ssm_client() -> Any:
    """Return a cached SSM client."""
    global _ssm_client
    if _ssm_client is None:
        _ssm_client = _create_boto3_client("ssm")
    return _ssm_client


def clear_credentials_cache() -> None:
    """Drop cached SSM parameter values."""
    _ssm_cache.clear()


def _read_ssm_parameters(names: list[str]) -> dict[str, str]:
    """Read SecureString parameters from SSM, using the in-memory cache."""
    now = time.monotonic()
    result: dict[str, str] = {}
    for name in names:
        cached = _ssm_cache.get(name)
        if cached and now < cached[1]:
            result[name] = cached[0]
    missing = [name for name in names if name not in result]
    if not missing:
        return result

    from botocore.exceptions import BotoCoreError, ClientError

    with _tracer.start_as_current_span("load_line_credentials_from_ssm"):
        try:
            response = _get_ssm_client().get_parameters(Names=missing, WithDecryption=True)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "Unknown")
            raise MissingCredentialError(
                f"Failed to read LINE credentials from SSM ({code})"
            ) from e
        except BotoCoreError as e:
            raise MissingCredentialError(
                f"Failed to read LINE credentials from SSM ({type(e).__name__})"
            ) from e

    if response.get("InvalidParameters"):
        raise MissingCredentialError(
            f"SSM parameter not found: {', '.join(response['InvalidParameters'])}"
        )

    expires_at = now + CREDENTIALS_CACHE_TTL_SECONDS
    for param in response["Parameters"]:
        _ssm_cache[param["Name"]] = (param["Value"], expires_at)
        result[param["Name"]] = param["Value"]
    logger.info("Loaded %d LINE credential(s) from SSM", len(response["Parameters"]))
    return result


def load_line_credentials() -> LineCredentials:
    """Resolve LINE credentials.

    Each value is taken from its environment variable (``LINE_CHANNEL_TOKEN`` /
    ``LINE_USER_ID``) if set, otherwise read from the SSM parameter named by
    ``LINE_CHANNEL_TOKEN_PARAM`` / ``LINE_USER_ID_PARAM``.

    Raises MissingCredentialError if any value cannot be resolved.
    """
    values: dict[str, str] = {}
    params: dict[str, str] = {}
    for field, (env_name, param_env_name) in _CREDENTIAL_SOURCES.items():
        if direct := os.environ.get(env_name):
            values[field] = direct
        elif param_name := os.environ.get(param_env_name):
            params[field] = param_name
        else:
            raise MissingCredentialError(
                f"{env_name} or {param_env_name} environment variable not set"
            )

    if params:
        fetched = _read_ssm_parameters(sorted(set(params.values())))
        for field, param_name in params.items():
            value = fetched.get(param_name)
            if not value:
                raise MissingCredentialError(f"SSM parameter is empty: {param_name}")
            values[field] = value

    return LineCredentials(values["channel_token"], values["user_id"])


# 同じリクエストの再送とみなす時間。この時間内に同じリクエストが届いたら、同じ再送キー
# （X-Line-Retry-Key）で LINE に送り、送信済みのバッチは LINE が送らずに 409 を返す。
# この時間を過ぎた再送は新しい再送キーで送るので、別のメッセージとして届く。
RETRY_KEY_TTL_SECONDS = 15 * 60

_dynamodb_client: Any = None


class RetryKeyError(Exception):
    """Raised when a retry key cannot be stored in or read from DynamoDB."""


def _get_dynamodb_client() -> Any:
    """Return a cached DynamoDB client."""
    global _dynamodb_client
    if _dynamodb_client is None:
        _dynamodb_client = _create_boto3_client("dynamodb")
    return _dynamodb_client


def _batch_key(user_id: str, messages: list[str], batch_index: int) -> str:
    """Return the key that identifies one batch of one request.

    送り先、リクエストのメッセージ全体、バッチの位置から作る。同じ内容のバッチが
    1つのリクエストに2回あっても、別のバッチとして扱う。リクエスト元は含めない
    （受け取る人は同じなので、別のシステムからの同じリクエストも重複として扱う）。
    """
    payload = json.dumps([user_id, messages, batch_index], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@_tracer.start_as_current_span("get_retry_key")
def get_retry_key(table_name: str, batch_key: str) -> str:
    """Return the retry key for the batch, creating one if none is valid.

    条件付き書き込みで、有効期限内の再送キーがなければ新しい再送キーを書く。
    すでにあれば（再送や、別の実行環境での同時の処理）、その再送キーを返す。
    DynamoDB の TTL による削除は遅れることがあるので、期限切れは expires_at で判定する。
    """
    now = int(time.time())
    retry_key = str(uuid.uuid4())

    from botocore.exceptions import BotoCoreError, ClientError

    try:
        _get_dynamodb_client().put_item(
            TableName=table_name,
            Item={
                "pk": {"S": batch_key},
                "retry_key": {"S": retry_key},
                "expires_at": {"N": str(now + RETRY_KEY_TTL_SECONDS)},
            },
            ConditionExpression="attribute_not_exists(pk) OR expires_at <= :now",
            ExpressionAttributeValues={":now": {"N": str(now)}},
            ReturnValuesOnConditionCheckFailure="ALL_OLD",
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        if code != "ConditionalCheckFailedException":
            raise RetryKeyError(f"Failed to store retry key in DynamoDB ({code})") from e
        existing = e.response.get("Item", {}).get("retry_key", {}).get("S")
        if not existing:
            raise RetryKeyError("Retry key not found in DynamoDB item") from e
        logger.info("Reusing retry key for a resent batch")
        trace.get_current_span().set_attribute("line.retry_key_reused", True)
        return existing
    except BotoCoreError as e:
        raise RetryKeyError(f"Failed to store retry key in DynamoDB ({type(e).__name__})") from e

    trace.get_current_span().set_attribute("line.retry_key_reused", False)
    return retry_key


def deliver_messages(
    raw_messages: list[str], channel_token: str, user_id: str, dry_run: bool = False
) -> LambdaResponse:
    """Validate, format, batch and push messages to LINE.

    dry_run が True のときは、LINE の validate API でバッチごとにメッセージを確認し、送信はしない。
    """
    if dry_run:
        # dry run のときだけ付ける。dry run のトレースは notify.dry_run=true で検索でき、
        # 通常の送信のトレースには属性が付かない
        trace.get_current_span().set_attribute("notify.dry_run", True)
    messages = validate_messages(raw_messages)
    if not messages:
        logger.warning("No valid messages after validation")
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "No valid messages to send"}),
        }

    formatted = format_line_messages(messages)
    batches = split_into_batches(formatted)
    trace.get_current_span().set_attribute("line.batch_count", len(batches))

    if dry_run:
        for i, batch in enumerate(batches, start=1):
            logger.debug("Validating batch %d/%d", i, len(batches))
            result = validate_push_messages(batch, channel_token)
            if result["statusCode"] != 200:
                logger.error("Dry run: batch %d failed validation: %s", i, result)
                return result

        logger.info(
            "Dry run: would send %d message(s) in %d batch(es)", len(messages), len(batches)
        )
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": f"Dry run: would send {len(messages)} message(s) "
                    f"in {len(batches)} batch(es)"
                }
            ),
        }

    # dry run の分は含めず、実際に送信したリクエストのバッチ数だけを記録する
    _batch_count_histogram.record(len(batches))
    logger.info("Sending %d message(s) in %d batch(es)", len(messages), len(batches))

    # 未設定のとき（ローカルで DynamoDB を使わないときなど）は再送キーを付けない
    table_name = os.environ.get("RETRY_KEY_TABLE_NAME")
    for i, batch in enumerate(batches, start=1):
        retry_key = None
        if table_name:
            try:
                retry_key = get_retry_key(table_name, _batch_key(user_id, messages, i))
            except RetryKeyError as e:
                logger.error("Batch %d: %s", i, e)
                return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
        logger.debug("Sending batch %d/%d", i, len(batches))
        result = push_messages(batch, channel_token, user_id, retry_key=retry_key)
        if result["statusCode"] == 409 and retry_key:
            # 同じ再送キーのリクエストを LINE がすでに受け付けている（送信済み）
            logger.info("Batch %d/%d was already sent, skipping", i, len(batches))
            continue
        if result["statusCode"] != 200:
            logger.error("Batch %d failed: %s", i, result)
            return result

    # 再送でも、最初のリクエストと同じレスポンスを返す
    logger.info("All messages sent successfully")
    return {
        "statusCode": 200,
        "body": json.dumps({"message": f"Successfully sent {len(messages)} message(s)"}),
    }


@_tracer.start_as_current_span("handle_notify")
def handle_notify(event: LambdaEvent) -> LambdaResponse:
    """Handle POST /notify: send messages via LINE."""
    try:
        channel_token, user_id = load_line_credentials()
    except MissingCredentialError as e:
        logger.error("%s", e)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

    try:
        request = parse_request(event)
    except ValueError as e:
        logger.warning("Failed to parse request: %s", e)
        return {
            "statusCode": 400,
            "body": json.dumps({"error": str(e)}),
        }

    return deliver_messages(request.messages, channel_token, user_id, dry_run=request.dry_run)


@_tracer.start_as_current_span("handle_scheduled")
def handle_scheduled(event: ScheduledEvent) -> LambdaResponse:
    """Handle a direct invocation from EventBridge Scheduler.

    Raises ScheduledNotificationError on failure so that the asynchronous
    invocation is recorded as an error (and retried by Lambda).
    """
    schedule_arn = event.get("schedule_arn")
    if schedule_arn:
        trace.get_current_span().set_attribute("scheduler.schedule_arn", schedule_arn)
    logger.info("Scheduled invocation (schedule_arn=%s)", schedule_arn)

    try:
        channel_token, user_id = load_line_credentials()
    except MissingCredentialError as e:
        logger.error("%s", e)
        raise ScheduledNotificationError(str(e)) from e

    raw_messages = event.get("messages")
    if not isinstance(raw_messages, list) or not all(isinstance(m, str) for m in raw_messages):
        raise ScheduledNotificationError("Scheduled event must have 'messages' as a list of str")

    result = deliver_messages(raw_messages, channel_token, user_id)
    if result["statusCode"] != 200:
        raise ScheduledNotificationError(result["body"])
    return result


def is_scheduled_event(event: LambdaEvent | ScheduledEvent) -> TypeIs[ScheduledEvent]:
    """Return True if the event was sent by EventBridge Scheduler."""
    return event.get("source") == SCHEDULER_EVENT_SOURCE


def lambda_handler(event: LambdaEvent | ScheduledEvent, context: Any) -> LambdaResponse:
    """Route requests to the appropriate handler."""
    logger.info("Lambda invoked")

    if is_scheduled_event(event):
        return handle_scheduled(event)

    if event.get("httpMethod") == "GET" and event.get("path") == "/docs":
        return serve_docs()

    if event.get("httpMethod") == "POST" and event.get("path") == "/webhook":
        return handle_webhook(event)

    return handle_notify(event)
