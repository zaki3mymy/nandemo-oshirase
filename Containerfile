# uv の公式イメージの python3.13-bookworm-slim のタグは、uv 0.10 以降は更新されていない（uv 0.9.30 のまま）。
# そのため Python のイメージに uv の実行ファイルだけをコピーする。uv のバージョンは
# pyproject.toml の [tool.uv] required-version の範囲に合わせる（上げるときは両方を変える）
FROM python:3.13-slim-bookworm AS deps-builder
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o requirements.txt

FROM node:20-slim AS docs-builder

# /docs に表示するバージョン（例: podman build --build-arg VERSION=$(git describe --tags) .）
ARG VERSION=dev
WORKDIR /docs
COPY openapi.yaml scripts/build-docs.sh ./
RUN ./build-docs.sh "$VERSION" docs.html openapi.yaml

FROM public.ecr.aws/lambda/python:3.13

COPY --from=deps-builder /app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/nandemo_oshirase/ ${LAMBDA_TASK_ROOT}/nandemo_oshirase/
COPY --from=docs-builder /docs/docs.html ${LAMBDA_TASK_ROOT}/nandemo_oshirase/docs.html
# 利用数を取得する Lambda（podman-compose の lambda-quota）も、同じイメージで command を変えて動かす
COPY src/nandemo_oshirase_quota/ ${LAMBDA_TASK_ROOT}/nandemo_oshirase_quota/

CMD ["nandemo_oshirase.lambda_function.lambda_handler"]
