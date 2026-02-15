# SageMaker inference container for StereoCrafter.
# Contract: GET /ping, POST /invocations with JSON {s3_input_uri, s3_output_uri}.
# Handler reads segment from S3, runs inference, writes result to S3.
#
# This Dockerfile uses a minimal Python image for the stub. For production:
# - Use a CUDA 11.8 base (e.g. nvidia/cuda:11.8-cudnn8-runtime-ubuntu22.04 or
#   a SageMaker PyTorch inference image).
# - Clone StereoCrafter, install Forward-Warp (dependency/Forward-Warp/install.sh),
#   install requirements.txt.
# - At startup: if HF_TOKEN_ARN is set, fetch secret and download weights from
#   Hugging Face (SVD, DepthCrafter, StereoCrafter) into /opt/ml/model/weights.
# - Replace the stub in serve.py with the real two-stage pipeline.

FROM python:3.11-slim

WORKDIR /opt/ml/code

RUN pip install --no-cache-dir boto3 gunicorn

# Build context is repo root (nx run stereocrafter-sagemaker:build)
COPY packages/stereocrafter-sagemaker/serve.py .

# SageMaker uses port 8080 and invokes the container with command "serve".
# Use ENTRYPOINT so that "docker run <image> serve" still runs gunicorn (otherwise
# "serve" would replace CMD and the container would try to run a missing executable).
ENV SAGEMAKER_BIND_TO_PORT=8080
EXPOSE 8080

ENTRYPOINT ["/bin/sh", "-c", "exec gunicorn --bind 0.0.0.0:8080 --workers 1 --timeout 3600 serve:application"]
