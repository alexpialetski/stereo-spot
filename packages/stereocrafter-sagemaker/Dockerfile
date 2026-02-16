# SageMaker inference container for StereoCrafter (production).
# Contract: GET /ping, POST /invocations with JSON {s3_input_uri, s3_output_uri, mode?}.
# Weights downloaded at startup from Hugging Face when HF_TOKEN_ARN is set.

# Use NVCR (nvcr.io) to avoid Docker Hub anonymous rate limit (429) in CodeBuild
FROM nvcr.io/nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV CUDA_HOME=/usr/local/cuda

# Python 3.10, git, build deps for Forward-Warp, libGL for opencv (cv2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-dev python3.10-venv python3-pip \
    git git-lfs \
    build-essential \
    libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && ln -sf /usr/bin/python3.10 /usr/bin/python3

# Clone StereoCrafter with submodules (DepthCrafter, Forward-Warp)
WORKDIR /opt
RUN git clone --recursive https://github.com/TencentARC/StereoCrafter.git stereocrafter

# Install StereoCrafter Python deps first (Forward-Warp install.sh needs torch for CUDA extension)
WORKDIR /opt/stereocrafter
RUN pip install --no-cache-dir -r requirements.txt

# Install Forward-Warp (CUDA extension; requires torch from previous step)
# TORCH_CUDA_ARCH_LIST needed: CodeBuild has no GPU, so PyTorch can't auto-detect archs.
# Must export: VAR=value cmd1 && cmd2 does NOT pass VAR to cmd2; use export for the whole chain.
WORKDIR /opt/stereocrafter/dependency/Forward-Warp
RUN export TORCH_CUDA_ARCH_LIST="7.0 7.5 8.0 8.6" && chmod +x install.sh && ./install.sh

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
