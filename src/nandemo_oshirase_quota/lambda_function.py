"""Record the LINE Messaging API's monthly message usage and limit as OTel metrics.

EventBridge Scheduler が1日1回（prod だけ）呼び出す。dev と prod は同じ LINE チャネルを
使っているので、上限も共有している。値はチャネル単位なので、どちらの環境から取っても同じになる。
"""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, NamedTuple, TypedDict

from opentelemetry import metrics, trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.sdk._logs import LoggerProvider

logger = logging.getLogger(__name__)
_log_level = logging.getLevelNamesMapping().get(
    os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO
)
logger.setLevel(_log_level)

# 実行の終わりにログを flush するときに待つ最大の時間。送り先は同じ実行環境の Collector（localhost）
LOG_FLUSH_TIMEOUT_MILLIS = 5000

# LINE API の呼び出しを待つ最大の時間（秒）。Lambda のタイムアウトより短くする
LINE_API_TIMEOUT_SECONDS = 10

_tracer = trace.get_tracer("nandemo_oshirase_quota")
_meter = metrics.get_meter("nandemo_oshirase_quota")

# 値は1日1回しか届かないので、Grafana では last_over_time(...[25h]) で読む。
# unit を "1" にすると Prometheus 側で名前に _ratio が付くので、{message} にする
# （{} で囲んだ unit は Prometheus の名前には付かない）
_consumption_gauge = _meter.create_gauge(
    "line.quota.consumption",
    unit="{message}",
    description="Approximate number of LINE messages sent in the current month",
)
_limit_gauge = _meter.create_gauge(
    "line.quota.limit",
    unit="{message}",
    description="Target limit of LINE messages that can be sent in the current month",
)


class QuotaError(Exception):
    """Raised when the usage or limit cannot be fetched.

    Lambda をエラーにして、Scheduler のリトライと Lambda の Errors メトリクスに任せる。
    """


class Quota(NamedTuple):
    total_usage: int
    # 上限が設定されていない（LINE の type が none）ときは None
    limit: int | None


class LambdaResult(TypedDict):
    totalUsage: int
    limit: int | None


def _create_ssm_client() -> Any:
    """Create an SSM client (boto3 is provided by the Lambda runtime)."""
    with _tracer.start_as_current_span("create_ssm_client"):
        import boto3

        return boto3.client("ssm")


def load_channel_token() -> str:
    """Resolve the LINE channel access token.

    環境変数 ``LINE_CHANNEL_TOKEN`` があればそれを使い（ローカル実行用）、なければ
    ``LINE_CHANNEL_TOKEN_PARAM`` の名前の SSM パラメータ（SecureString）を読む。
    1日1回しか呼ばれないので、送信の Lambda と違ってキャッシュしない。
    """
    if direct := os.environ.get("LINE_CHANNEL_TOKEN"):
        return direct
    param_name = os.environ.get("LINE_CHANNEL_TOKEN_PARAM")
    if not param_name:
        raise QuotaError(
            "LINE_CHANNEL_TOKEN or LINE_CHANNEL_TOKEN_PARAM environment variable not set"
        )

    from botocore.exceptions import BotoCoreError, ClientError

    client = _create_ssm_client()
    with _tracer.start_as_current_span("load_line_channel_token_from_ssm"):
        try:
            response = client.get_parameter(Name=param_name, WithDecryption=True)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "Unknown")
            raise QuotaError(f"Failed to read the LINE channel token from SSM ({code})") from e
        except BotoCoreError as e:
            raise QuotaError(
                f"Failed to read the LINE channel token from SSM ({type(e).__name__})"
            ) from e

    value = response["Parameter"]["Value"]
    if not value:
        raise QuotaError(f"SSM parameter is empty: {param_name}")
    return value


def _get_line_api(path: str, channel_token: str) -> dict[str, Any]:
    """GET a LINE Messaging API endpoint and return the JSON body."""
    base_url = os.environ.get("LINE_API_BASE_URL", "https://api.line.me")
    request = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Authorization": f"Bearer {channel_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=LINE_API_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise QuotaError(f"LINE API {path} error: status={e.code} reason={e.reason}") from e
    except urllib.error.URLError as e:
        raise QuotaError(f"LINE API {path} connection error: {e.reason}") from e

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise QuotaError(f"LINE API {path} returned invalid JSON") from e
    if not isinstance(data, dict):
        raise QuotaError(f"LINE API {path} returned an unexpected body: {body}")
    return data


def _require_int(data: dict[str, Any], key: str, path: str) -> int:
    value = data.get(key)
    # bool は int のサブクラスなので除く
    if not isinstance(value, int) or isinstance(value, bool):
        raise QuotaError(f"LINE API {path} returned an unexpected {key}: {value!r}")
    return value


@_tracer.start_as_current_span("get_message_quota")
def get_message_quota(channel_token: str) -> int | None:
    """Return the target limit for the current month, or None if no limit is set."""
    path = "/v2/bot/message/quota"
    data = _get_line_api(path, channel_token)
    match data.get("type"):
        case "limited":
            return _require_int(data, "value", path)
        case "none":
            return None
        case other:
            raise QuotaError(f"LINE API {path} returned an unexpected type: {other!r}")


@_tracer.start_as_current_span("get_message_consumption")
def get_message_consumption(channel_token: str) -> int:
    """Return the approximate number of messages sent in the current month.

    LINE Official Account Manager から送った分も含む。
    """
    path = "/v2/bot/message/quota/consumption"
    return _require_int(_get_line_api(path, channel_token), "totalUsage", path)


def fetch_quota() -> Quota:
    channel_token = load_channel_token()
    return Quota(
        total_usage=get_message_consumption(channel_token),
        limit=get_message_quota(channel_token),
    )


def record_quota(quota: Quota) -> None:
    span = trace.get_current_span()
    span.set_attribute("line.quota.total_usage", quota.total_usage)
    _consumption_gauge.set(quota.total_usage)
    if quota.limit is not None:
        span.set_attribute("line.quota.limit", quota.limit)
        _limit_gauge.set(quota.limit)
    logger.info("LINE message quota: total_usage=%d limit=%s", quota.total_usage, quota.limit)


def flush_logs() -> None:
    """Flush OTel logs before Lambda freezes the execution environment.

    The Lambda instrumentation flushes only traces and metrics, so logs batched by the SDK
    would wait until the next invocation (or be lost when the environment shuts down).
    """
    provider = get_logger_provider()
    # opentelemetry-instrument を通さない（SDK が設定されていない）ときは、API の
    # ProxyLoggerProvider が返るので flush しない
    if isinstance(provider, LoggerProvider):
        provider.force_flush(timeout_millis=LOG_FLUSH_TIMEOUT_MILLIS)


def lambda_handler(event: Any, context: Any) -> LambdaResult:
    try:
        logger.info("Lambda invoked")
        quota = fetch_quota()
        record_quota(quota)
        return {"totalUsage": quota.total_usage, "limit": quota.limit}
    finally:
        flush_logs()
