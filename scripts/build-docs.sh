#!/usr/bin/env bash
# openapi.yaml の info.version にバージョンを入れて、ドキュメント（/docs の HTML）をビルドする。
#
#   scripts/build-docs.sh <バージョン> [出力先] [OpenAPI のファイル]
#
# openapi.yaml の info.version はプレースホルダー（0.0.0-dev）にしてあり、
# リポジトリにはバージョンを書かない。CD は git のタグからバージョンを決めて渡す。
set -euo pipefail

version="${1:?usage: $0 <version> [output] [spec]}"
output="${2:-src/nandemo_oshirase/docs.html}"
spec="${3:-openapi.yaml}"

placeholder='  version: "0.0.0-dev"'

# sed の置換と YAML の文字列に入れるので、使える文字を絞る（例: v1.2.1、v1.2.1-3-gabc1234、dev）
if ! [[ "$version" =~ ^[0-9A-Za-z][0-9A-Za-z.+_-]*$ ]]; then
  echo "error: invalid version '$version'" >&2
  exit 1
fi

# プレースホルダーがなければ、置き換えずに古いバージョンのまま出してしまうので失敗させる
if ! grep -qxF "$placeholder" "$spec"; then
  echo "error: placeholder '$placeholder' (info.version) not found in $spec" >&2
  exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
sed "s/^  version: \"0\.0\.0-dev\"\$/  version: \"$version\"/" "$spec" > "$tmp/openapi.yaml"

npx --yes @redocly/cli build-docs "$tmp/openapi.yaml" --output "$output"
echo "Built $output (version: $version)"
