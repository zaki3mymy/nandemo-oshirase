#!/usr/bin/env python3
"""OTel のコミュニティの Python 計装レイヤーに無い計装を入れた Lambda レイヤーの zip を作る。

コミュニティのレイヤーに入っていない、次の計装を自前のレイヤーで足す（docs/deployment.md を参照）。

- opentelemetry-instrumentation-urllib: 無いと、LINE API の呼び出しの span が出ない
- opentelemetry-instrumentation-logging: 無いと、logging のログが OTel のログとして送られない

- バージョンは uv.lock のものを使う。uv.lock の OTel の依存は、
  コミュニティのレイヤーと同じバージョンに固定している
- 依存するパッケージ（opentelemetry-instrumentation など）は
  コミュニティのレイヤーにあるので、--no-deps で入れる
- zip は、同じバージョンなら毎回同じ中身（ハッシュ）になるように作る。
  Terraform の source_code_hash が変わらなければ、レイヤーは作り直されない

使い方: python3 scripts/build-otel-instrumentations-layer.py [出力する zip のパス]
"""

import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

PACKAGES = [
    "opentelemetry-instrumentation-urllib",
    "opentelemetry-instrumentation-logging",
]
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "dist" / "otel-instrumentations-layer.zip"
# zip のエントリーに付ける固定の日時（zip の形式で表せる一番古い日時）
FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def locked_version(lock_path: Path, package: str) -> str:
    lock = tomllib.loads(lock_path.read_text())
    for pkg in lock.get("package", []):
        if pkg["name"] == package:
            return pkg["version"]
    raise SystemExit(f"{package} が {lock_path} にありません")


def build(output: Path) -> list[str]:
    requirements = [f"{p}=={locked_version(ROOT / 'uv.lock', p)}" for p in PACKAGES]
    with tempfile.TemporaryDirectory() as tmp:
        # レイヤーの中身は /opt/python に展開される
        target = Path(tmp) / "python"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--quiet",
                "--no-deps",
                # .pyc を作らない（.pyc にはインストールした日時が入り、zip の中身が毎回変わるため）
                "--no-compile",
                "--target",
                str(target),
                *requirements,
            ],
            check=True,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        files = sorted(p for p in Path(tmp).rglob("*") if p.is_file())
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in files:
                info = zipfile.ZipInfo(path.relative_to(tmp).as_posix(), date_time=FIXED_DATE_TIME)
                info.external_attr = 0o644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, path.read_bytes())
    return requirements


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    for req in build(out):
        print(f"{req} -> {out}")
