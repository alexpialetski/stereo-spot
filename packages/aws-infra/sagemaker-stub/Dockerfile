# Minimal SageMaker stub: GET /ping and POST /invocations on 8080.
# SageMaker runs "docker run <image> serve", which overrides CMD; use ENTRYPOINT so our server always runs.
FROM alpine:3.19
RUN apk add --no-cache python3
ENV SAGEMAKER_BIND_TO_PORT=8080
EXPOSE 8080
COPY server.py .
ENTRYPOINT ["python3", "server.py"]
CMD ["serve"]
