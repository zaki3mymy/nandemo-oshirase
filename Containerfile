FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS deps-builder

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project && \
    sed -i '1s|.*|#!/var/lang/bin/python3|' .venv/bin/opentelemetry-instrument

FROM node:20-slim AS docs-builder

WORKDIR /docs
COPY openapi.yaml .
RUN npx --yes @redocly/cli build-docs openapi.yaml --output docs.html

FROM public.ecr.aws/lambda/python:3.13

ENV PYTHONPATH=${LAMBDA_TASK_ROOT}

COPY --from=deps-builder /app/.venv/lib/python3.13/site-packages/ ${LAMBDA_TASK_ROOT}/
COPY --from=deps-builder /app/.venv/bin/opentelemetry-instrument /usr/local/bin/opentelemetry-instrument
COPY src/nandemo_oshirase/ ${LAMBDA_TASK_ROOT}/nandemo_oshirase/
COPY --from=docs-builder /docs/docs.html ${LAMBDA_TASK_ROOT}/nandemo_oshirase/docs.html

CMD ["nandemo_oshirase.lambda_function.lambda_handler"]
