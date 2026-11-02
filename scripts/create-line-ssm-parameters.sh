#!/usr/bin/env bash
# Issue #53 ステップ0: 環境ごとの LINE パラメータを SSM Parameter Store に作成する。
#
# 各環境の Lambda 関数（tf/modules/main.tf の "${stage_name}-${project_name}-function"）
# の環境変数 LINE_CHANNEL_TOKEN / LINE_USER_ID の値を読み、次の SecureString として登録する。
#
#   /app/nandemo_oshirase/<stage>/line_channel_token
#   /app/nandemo_oshirase/<stage>/line_user_id
#
# 使い方:
#   scripts/create-line-ssm-parameters.sh [--dry-run] [--overwrite] [stage ...]
#     stage      対象の環境（既定: dev prod）
#     --dry-run  読み取りだけ行い、登録はしない
#     --overwrite 既存のパラメータを上書きする（既定では既存ならスキップ）
#
# 環境変数:
#   AWS_REGION    既定 ap-northeast-1
#   AWS_PROFILE   必要に応じて指定
#   PROJECT_NAME  既定 nandemo-oshirase
#
# 値そのものは標準出力に出さない（文字数のみ表示する）。
set -euo pipefail

REGION="${AWS_REGION:-ap-northeast-1}"
PROJECT_NAME="${PROJECT_NAME:-nandemo-oshirase}"
PARAM_PREFIX="/app/nandemo_oshirase"

DRY_RUN=false
OVERWRITE=false
STAGES=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --overwrite) OVERWRITE=true ;;
    -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
    dev|prod) STAGES="$STAGES $arg" ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done
[[ -z "$STAGES" ]] && STAGES="dev prod"

# 環境変数名 → パラメータ名の末尾（macOS の bash 3.2 でも動くよう連想配列は使わない）
param_suffix() {
  case "$1" in
    LINE_CHANNEL_TOKEN) echo line_channel_token ;;
    LINE_USER_ID) echo line_user_id ;;
  esac
}

get_lambda_env() {
  local function_name="$1" var_name="$2"
  aws lambda get-function-configuration \
    --region "$REGION" \
    --function-name "$function_name" \
    --query "Environment.Variables.${var_name}" \
    --output text
}

parameter_exists() {
  local name="$1"
  [[ "$(aws ssm get-parameters --region "$REGION" --names "$name" \
        --query 'length(Parameters)' --output text)" != "0" ]]
}

get_parameter_value() {
  aws ssm get-parameter --region "$REGION" --name "$1" --with-decryption \
    --query 'Parameter.Value' --output text
}

echo "region: $REGION"
aws sts get-caller-identity --query 'Arn' --output text | sed 's/^/caller: /'

for stage in $STAGES; do
  function_name="${stage}-${PROJECT_NAME}-function"
  echo
  echo "== ${stage} (${function_name})"

  for var_name in LINE_CHANNEL_TOKEN LINE_USER_ID; do
    param_name="${PARAM_PREFIX}/${stage}/$(param_suffix "$var_name")"
    value="$(get_lambda_env "$function_name" "$var_name")"

    if [[ -z "$value" || "$value" == "None" ]]; then
      echo "ERROR: ${function_name} に環境変数 ${var_name} がありません" >&2
      exit 1
    fi
    echo "  ${var_name} (${#value} chars) -> ${param_name}"

    if $DRY_RUN; then
      continue
    fi

    overwrite_opt=--no-overwrite
    if parameter_exists "$param_name"; then
      if ! $OVERWRITE; then
        echo "    skip: すでに存在します（上書きするには --overwrite）"
        continue
      fi
      overwrite_opt=--overwrite
    fi

    aws ssm put-parameter \
      --region "$REGION" \
      --name "$param_name" \
      --type SecureString \
      --value "$value" \
      "$overwrite_opt" \
      --query 'Version' --output text | sed 's/^/    put: version /'

    if [[ "$(get_parameter_value "$param_name")" == "$value" ]]; then
      echo "    verified"
    else
      echo "ERROR: ${param_name} の値が Lambda の環境変数と一致しません" >&2
      exit 1
    fi
  done
done
