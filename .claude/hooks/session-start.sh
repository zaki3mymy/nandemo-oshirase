#!/bin/bash
# Claude Code クラウドセッション用: flake.nix の dev-tools (terraform, uv など) を
# Claude の Bash ツールから使えるようにし、Python 依存と Terraform プロバイダを用意する
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"
export PATH="/nix/var/nix/profiles/default/bin:$PATH"

if ! command -v nix >/dev/null 2>&1; then
  echo "session-start: nix が見つからないため dev-tools の読み込みをスキップします" >&2
  exit 0
fi

# dev-tools へのリンク (git 管理外。Nix の GC ルートにもなる)。
# uv は Python の無い .venv を受け付けないので、.venv の外に置く
tools="$PWD/.nix-dev-tools"
hashes=.venv/.session-start.sha256

export UV_PYTHON="$tools/bin/python3"
export UV_PYTHON_DOWNLOADS=never
unset PYTHONPATH

if ! sha256sum --check --status "$hashes" 2>/dev/null || [ ! -x "$tools/bin/terraform" ]; then
  # 先に古いハッシュを消し、途中で失敗したら次回やり直す
  rm -f "$hashes"

  nix build .#dev-tools --out-link "$tools"
  PATH="$tools/bin:$PATH" uv sync --dev

  sha256sum .claude/hooks/session-start.sh flake.nix flake.lock pyproject.toml uv.lock \
    > "$hashes" || rm -f "$hashes"
fi

# 以降は毎セッション実行する
export PATH="$tools/bin:$PATH"

# terraform validate に必要なプロバイダ (.terraform は git 管理外)
for dir in tf/envs/*/; do
  if [ ! -d "$dir.terraform/providers" ]; then
    terraform -chdir="$dir" init -backend=false -input=false >/dev/null
  fi
done

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    printf 'export PATH=%q:"$PATH"\n' "$tools/bin"
    printf 'export UV_PYTHON=%q\n' "$UV_PYTHON"
    printf 'export UV_PYTHON_DOWNLOADS=never\n'
    printf 'unset PYTHONPATH\n'
  } >> "$CLAUDE_ENV_FILE"
fi
