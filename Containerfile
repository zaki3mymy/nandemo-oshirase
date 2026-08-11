FROM node:20-slim AS docs-builder

WORKDIR /docs
COPY openapi.yaml .
RUN npx --yes @redocly/cli build-docs openapi.yaml --output docs.html

FROM public.ecr.aws/lambda/python:3.13

COPY src/nandemo_oshirase/ ${LAMBDA_TASK_ROOT}/nandemo_oshirase/
COPY --from=docs-builder /docs/docs.html ${LAMBDA_TASK_ROOT}/nandemo_oshirase/docs.html

CMD ["nandemo_oshirase.lambda_function.lambda_handler"]
