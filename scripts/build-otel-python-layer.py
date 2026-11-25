#!/usr/bin/env python3
"""OTel の Python の Lambda レイヤーの zip を作る（コミュニティの Python 計装レイヤーの代わり）。

コミュニティのレイヤー（opentelemetry-lambda）は python3.14 で作られていて、
入っている .pyc は python3.14 用（cpython-314）しかない。python3.13 の Lambda ではそれを使えず、
/opt は書き込めないので、コールドスタートのたびにレイヤーのモジュールを
すべてコンパイルし直していた。
そのため、python3.13 用の .pyc を入れたレイヤーを自前で作る（docs/deployment.md を参照）。

- 入れるパッケージは、uv.lock のアプリの依存（OTel のパッケージとその依存）。
  boto3・botocore・urllib3 など、Lambda のランタイムにあるものは入れない
  （コミュニティのレイヤーと同じ）
- Lambda（x86_64、python3.13）で動く wheel を入れる。ビルドする環境の Python は使わない
- ハンドラーのラッパー（otel-handler など）は、layers/otel-python からそのまま入れる
- .pyc は、ソースのハッシュで検証する形（unchecked-hash）で、/opt/python のパスで作る。
  作った日時やビルドしたディレクトリが入らないので、同じ uv.lock・同じ Python なら
  zip の中身（ハッシュ）は毎回同じになり、Terraform はレイヤーを作り直さない

python3.13 で実行する（.pyc はそれを作った Python のバージョンでしか使えないため）。
使い方: uv run --no-project --python 3.13 scripts/build-otel-python-layer.py [出力する zip のパス]
"""

import compileall
import py_compile
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRAPPER_DIR = ROOT / "layers" / "otel-python"
DEFAULT_OUTPUT = ROOT / "dist" / "otel-python-layer.zip"
# Lambda のランタイム（python3.13）
PYTHON_VERSION = (3, 13)
PYTHON_PLATFORM = "x86_64-manylinux_2_34"
# レイヤーの中身は /opt に展開される。Python のパッケージは /opt/python に置く
LAYER_PYTHON_DIR = "/opt/python"
# Lambda のランタイムにあるので、レイヤーに入れないパッケージ
RUNTIME_PACKAGES = {
    "boto3",
    "botocore",
    "s3transfer",
    "jmespath",
    "python-dateutil",
    "six",
    "urllib3",
}
# zip のエントリーに付ける固定の日時（zip の形式で表せる一番古い日時）
FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)
# opentelemetry-instrument のコマンド。otel-instrument が python3 で実行する（pip が作るものは
# ビルドした環境の Python のパスが shebang に入るので、使わずに自分で置く）
INSTRUMENT_COMMAND = """\
import sys

from opentelemetry.instrumentation.auto_instrumentation import run

sys.exit(run())
"""


def requirements() -> list[str]:
    """uv.lock から、アプリの依存（dev などのグループを除く）を固定したバージョンで返す。"""
    out = subprocess.run(
        [
            "uv",
            "export",
            "--frozen",
            "--no-default-groups",
            "--no-emit-project",
            "--no-hashes",
            "--no-header",
            "--no-annotate",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    lines = [line.strip() for line in out.splitlines()]
    reqs = [line for line in lines if line and not line.startswith("#")]
    return [r for r in reqs if r.split("==")[0].lower() not in RUNTIME_PACKAGES]


def build(output: Path) -> list[str]:
    if sys.version_info[:2] != PYTHON_VERSION:
        version = ".".join(map(str, PYTHON_VERSION))
        raise SystemExit(
            f"python{version} で実行してください（.pyc はそれを作った Python でしか使えません）"
        )

    reqs = requirements()
    with tempfile.TemporaryDirectory() as tmp:
        layer = Path(tmp)
        python_dir = layer / "python"
        req_file = layer / "requirements.txt"
        req_file.write_text("\n".join(reqs) + "\n")
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--quiet",
                "--target",
                str(python_dir),
                "--python",
                sys.executable,
                "--python-platform",
                PYTHON_PLATFORM,
                "--only-binary",
                ":all:",
                # 依存はすべて requirements に固定したバージョンで並んでいる
                "--no-deps",
                "--no-compile",
                "-r",
                str(req_file),
            ],
            check=True,
        )
        req_file.unlink()

        # bin のコマンドは使わないので消す。RECORD からも消す（コマンドの shebang には
        # ビルドした環境の Python のパスが入り、その sha256 が RECORD に載るので、
        # 残すと zip の中身が環境によって変わる）
        shutil.rmtree(python_dir / "bin", ignore_errors=True)
        for record in python_dir.glob("*.dist-info/RECORD"):
            lines = record.read_text().splitlines(keepends=True)
            record.write_text("".join(line for line in lines if not line.startswith("bin/")))
        (python_dir / "bin").mkdir()
        (python_dir / "bin" / "opentelemetry-instrument").write_text(INSTRUMENT_COMMAND)
        shutil.copy(WRAPPER_DIR / "otel_wrapper.py", python_dir / "otel_wrapper.py")
        for script in ("otel-handler", "otel-instrument"):
            shutil.copy(WRAPPER_DIR / script, layer / script)

        ok = compileall.compile_dir(
            python_dir,
            quiet=2,
            ddir=LAYER_PYTHON_DIR,
            invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
        )
        if not ok:
            raise SystemExit(".pyc を作れないファイルがありました")

        output.parent.mkdir(parents=True, exist_ok=True)
        files = sorted(p for p in layer.rglob("*") if p.is_file())
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in files:
                name = path.relative_to(layer).as_posix()
                info = zipfile.ZipInfo(name, date_time=FIXED_DATE_TIME)
                # ラッパーのスクリプトは AWS_LAMBDA_EXEC_WRAPPER で実行されるので、
                # 実行できるようにする
                mode = 0o755 if name in ("otel-handler", "otel-instrument") else 0o644
                info.external_attr = mode << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, path.read_bytes())
    return reqs


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    for req in build(out):
        print(req)
    print(f"-> {out}")
