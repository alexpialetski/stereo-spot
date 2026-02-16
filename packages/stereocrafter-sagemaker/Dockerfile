# SageMaker inference container for StereoCrafter (production).
# Contract: GET /ping, POST /invocations with JSON {s3_input_uri, s3_output_uri, mode?}.
# Weights downloaded at startup from Hugging Face when HF_TOKEN_ARN is set.

FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV CUDA_HOME=/usr/local/cuda

# Python 3.10, git, build deps for Forward-Warp
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-venv python3-pip \
    git git-lfs \
    build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && ln -sf /usr/bin/python3.10 /usr/bin/python3

# Clone StereoCrafter with submodules (DepthCrafter, Forward-Warp)
WORKDIR /opt
RUN git clone --recursive https://github.com/TencentARC/StereoCrafter.git stereocrafter

# Install Forward-Warp (CUDA extension)
WORKDIR /opt/stereocrafter/dependency/Forward-Warp
RUN chmod +x install.sh && ./install.sh

# Install StereoCrafter Python deps
WORKDIR /opt/stereocrafter
RUN pip install --no-cache-dir -r requirements.txt

# SageMaker app deps
RUN pip install --no-cache-dir boto3 gunicorn huggingface_hub

WORKDIR /opt/ml/code

COPY packages/stereocrafter-sagemaker/serve.py .
COPY packages/stereocrafter-sagemaker/download_weights.py .

ENV SAGEMAKER_BIND_TO_PORT=8080
ENV PYTHONPATH=/opt/stereocrafter
ENV WEIGHTS_DIR=/opt/ml/model/weights
EXPOSE 8080

# At startup: download weights if HF_TOKEN_ARN set; then serve
ENTRYPOINT ["/bin/sh", "-c", "python /opt/ml/code/download_weights.py || true; exec gunicorn --bind 0.0.0.0:8080 --workers 1 --timeout 3600 serve:application"]
