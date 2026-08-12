FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS deps-builder

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o requirements.txt

FROM node:20-slim AS docs-builder

WORKDIR /docs
COPY openapi.yaml .
RUN npx --yes @redocly/cli build-docs openapi.yaml --output docs.html

FROM public.ecr.aws/lambda/python:3.13

COPY --from=deps-builder /app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/nandemo_oshirase/ ${LAMBDA_TASK_ROOT}/nandemo_oshirase/
COPY --from=docs-builder /docs/docs.html ${LAMBDA_TASK_ROOT}/nandemo_oshirase/docs.html

CMD ["nandemo_oshirase.lambda_function.lambda_handler"]
