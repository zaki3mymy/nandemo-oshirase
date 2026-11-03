#!/bin/bash
# Claude Code クラウドセッション用: flake.nix の devShell のツールを
# Claude の Bash ツールから使えるよう、PATH とこのリポジトリが必要とする環境変数を設定する。
#
# ツールの取得は環境のセットアップスクリプト (dotfiles の setup-nix-devshells.sh) の担当。
# 取得されていなくても、ここで nix が必要なものを取りに行く。
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ] || [ -z "${CLAUDE_ENV_FILE:-}" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"
export PATH="/nix/var/nix/profiles/default/bin:$PATH"

if ! command -v nix >/dev/null 2>&1 || [ ! -f flake.nix ]; then
  exit 0
fi

# devShell の中身 (packages に書いたツールのストアパスと env の値) を取り出す
devenv="$(nix --extra-experimental-features "nix-command flakes" print-dev-env --json)"

# devShell の PATH には mkShell の土台の coreutils なども入るので使わず、
# packages / buildInputs に書いたものの bin だけを足す
bins="$(jq -r '
  [.variables.nativeBuildInputs.value, .variables.buildInputs.value]
  | map(select(. != null) | split(" ")[]) | map(select(. != "") | . + "/bin") | join(":")
' <<<"$devenv")"

{
  printf 'export PATH=%q:"$PATH"\n' "$bins"
  # flake.nix の devShell の env に書いた、このリポジトリで使う環境変数
  for var in UV_PYTHON UV_PYTHON_DOWNLOADS; do
    value="$(jq -r --arg v "$var" '.variables[$v].value // empty' <<<"$devenv")"
    [ -n "$value" ] && printf 'export %s=%q\n' "$var" "$value"
  done
  # Nix の Python の site-packages が .venv のパッケージとぶつからないようにする
  printf 'unset PYTHONPATH\n'
} >> "$CLAUDE_ENV_FILE"
