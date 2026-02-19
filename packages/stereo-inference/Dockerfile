# Inference container for iw3 (nunif): 2D video to stereo SBS/anaglyph. Storage/metrics via adapters (AWS/GCP).
# Contract: GET /ping, POST /invocations with JSON {input_uri|s3_input_uri, output_uri|s3_output_uri, mode?}.
# See https://github.com/nagadomi/nunif (INSTALL-ubuntu.md, iw3/README.md).

FROM nvcr.io/nvidia/cuda:12.1.0-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

# Dependencies per installation_ubuntu.md (git-core, libmagickwand-dev, libraqm-dev, python3-dev)
# + Python 3.10 explicit + headless runtime libs for imaging
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-dev python3.10-venv python3-pip \
    git-core libmagickwand-dev libraqm-dev \
    libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && ln -sf /usr/bin/python3.10 /usr/bin/python3

# Clone nunif (iw3: 2D video to side-by-side 3D / anaglyph)
WORKDIR /opt
RUN git clone https://github.com/nagadomi/nunif.git

WORKDIR /opt/nunif

# PyTorch per nunif requirements-torch.txt (CUDA 12.8; works on 12.x drivers)
RUN pip install --no-cache-dir torch==2.7.1+cu128 torchvision==0.22.1+cu128 \
    --extra-index-url https://download.pytorch.org/whl/cu128

# Pip packages per requirements.txt (omit flake8, GUI, dev). Single RUN to reduce layers.
RUN pip install --no-cache-dir \
    requests tqdm scipy waitress bottle==0.12.25 diskcache psutil pyyaml platformdirs packaging filelock \
    timm "av==15.0.0" truststore pillow_heif safetensors einops omegaconf addict \
    boto3 gunicorn google-cloud-storage

# Pre-trained models for iw3 (ZoeDepth, Depth-Anything, etc.). Baked in so no network at startup.
ENV NUNIF_HOME=/opt/nunif_data
RUN mkdir -p "$NUNIF_HOME" && python -m iw3.download_models

WORKDIR /opt/ml/code
COPY packages/stereo-inference/*.py .

# Optional: set IW3_LOW_VRAM=1 for smaller GPU instances (e.g. g5.xlarge) to reduce OOM risk (iw3.md)
ENV SAGEMAKER_BIND_TO_PORT=8080
ENV NUNIF_HOME=/opt/nunif_data
EXPOSE 8080

ENTRYPOINT ["/bin/sh", "-c", "exec gunicorn --bind 0.0.0.0:8080 --workers 1 --timeout 3600 serve:application"]
