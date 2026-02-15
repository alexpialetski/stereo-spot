# Media worker: chunking (ffmpeg split) + reassembly (ffmpeg concat). One image for both.
# Build from repo root: docker build -f packages/media-worker/Dockerfile .
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Monorepo: copy and install shared-types and aws-adapters first
COPY packages/shared-types /shared-types
COPY packages/aws-adapters /aws-adapters
RUN pip install --no-cache-dir -e /shared-types -e /aws-adapters

COPY packages/media-worker /media-worker
RUN pip install --no-cache-dir -e /media-worker

ENV PYTHONUNBUFFERED=1
WORKDIR /media-worker
CMD ["python", "-m", "media_worker.main"]
