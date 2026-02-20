# Inference container for iw3 (nunif): 2D video to stereo SBS/anaglyph. Storage/metrics via adapters (AWS/GCP).
# Contract: GET /ping, POST /invocations with JSON {input_uri|s3_input_uri, output_uri|s3_output_uri, mode?}.
# See https://github.com/nagadomi/nunif (INSTALL-ubuntu.md, iw3/README.md).

FROM nvcr.io/nvidia/cuda:12.1.0-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

# Dependencies per installation_ubuntu.md (git-core, libmagickwand-dev, libraqm-dev, python3-dev)
# + Python 3.10 explicit + headless runtime libs for imaging
# + libnvidia-encode-470 for NVENC (h264_nvenc) on SageMaker ml.g4dn (driver 470); host may not mount it
# + build-essential, yasm, nasm, pkg-config for building FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-dev python3.10-venv python3-pip \
    git-core libmagickwand-dev libraqm-dev \
    libgl1-mesa-glx libglib2.0-0 \
    libnvidia-encode-470 \
    build-essential yasm nasm pkg-config wget xz-utils \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && ln -sf /usr/bin/python3.10 /usr/bin/python3

# Request full driver capabilities (including video/NVENC) so host runtime may mount libnvidia-encode
ENV NVIDIA_DRIVER_CAPABILITIES=all,video

# --- FFmpeg 5.1 + nv-codec-headers 11.1 so h264_nvenc works with SageMaker ml.g4dn (driver 470, NVENC API 11.1) ---
# Prebuilt PyAV/FFmpeg require NVENC 13.0; building FFmpeg with n11.1.5.2 headers targets API 11.1.
RUN cd /tmp \
    && wget -q https://github.com/FFmpeg/nv-codec-headers/archive/refs/tags/n11.1.5.2.tar.gz -O nv-codec-headers.tar.gz \
    && tar xzf nv-codec-headers.tar.gz && cd nv-codec-headers-n11.1.5.2 \
    && make install PREFIX=/usr/local && cd /tmp && rm -rf nv-codec-headers-n11.1.5.2 nv-codec-headers.tar.gz
RUN cd /tmp \
    && wget -q https://ffmpeg.org/releases/ffmpeg-5.1.2.tar.xz && tar xf ffmpeg-5.1.2.tar.xz && cd ffmpeg-5.1.2 \
    && ./configure --prefix=/usr/local --enable-nonfree --enable-nvenc --enable-shared --disable-static --disable-debug \
    && make -j"$(nproc)" && make install && cd /tmp && rm -rf ffmpeg-5.1.2 ffmpeg-5.1.2.tar.xz

# Clone nunif (iw3: 2D video to side-by-side 3D / anaglyph)
WORKDIR /opt
RUN git clone https://github.com/nagadomi/nunif.git

WORKDIR /opt/nunif

# PyTorch per nunif requirements-torch.txt (CUDA 12.8; works on 12.x drivers)
RUN pip install --no-cache-dir torch==2.7.1+cu128 torchvision==0.22.1+cu128 \
    --extra-index-url https://download.pytorch.org/whl/cu128

# Pip packages per requirements.txt (omit flake8, GUI, dev). Install av from source so it links to our FFmpeg (NVENC 11.1).
RUN pip install --no-cache-dir \
    requests tqdm scipy waitress bottle==0.12.25 diskcache psutil pyyaml platformdirs packaging filelock \
    timm truststore pillow_heif safetensors einops omegaconf addict \
    boto3 gunicorn google-cloud-storage \
    && PKG_CONFIG_PATH=/usr/local/lib/pkgconfig LD_LIBRARY_PATH=/usr/local/lib pip install --no-cache-dir --no-binary av "av==15.0.0"

# Pre-trained models for iw3 (ZoeDepth, Depth-Anything, etc.). Baked in so no network at startup.
ENV NUNIF_HOME=/opt/nunif_data
RUN mkdir -p "$NUNIF_HOME" && python -m iw3.download_models

WORKDIR /opt/ml/code
COPY packages/stereo-inference/*.py .

# Optional: set IW3_LOW_VRAM=1 for smaller GPU instances (e.g. g5.xlarge) to reduce OOM risk (iw3.md)
ENV SAGEMAKER_BIND_TO_PORT=8080
ENV NUNIF_HOME=/opt/nunif_data
EXPOSE 8080

# Prepend host-mounted NVIDIA lib path and our FFmpeg libs so libnvidia-encode and libavcodec are found
ENTRYPOINT ["/bin/sh", "-c", "export LD_LIBRARY_PATH=/usr/local/lib:${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}/usr/local/nvidia/lib64 && exec gunicorn --bind 0.0.0.0:8080 --workers 1 --timeout 3600 serve:application"]
