FROM public.ecr.aws/lambda/python:3.13

COPY src/nandemo_oshirase/ ${LAMBDA_TASK_ROOT}/nandemo_oshirase/

CMD ["nandemo_oshirase.lambda_function.lambda_handler"]
