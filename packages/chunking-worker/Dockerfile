# Chunking worker: ffmpeg + Python, consumes chunking queue and uploads segments to S3.
# Build from repo root: docker build -f packages/chunking-worker/Dockerfile .
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Monorepo: copy and install shared-types and aws-adapters first
COPY packages/shared-types /shared-types
COPY packages/aws-adapters /aws-adapters
RUN pip install --no-cache-dir -e /shared-types -e /aws-adapters

COPY packages/chunking-worker /chunking-worker
RUN pip install --no-cache-dir -e /chunking-worker

ENV PYTHONUNBUFFERED=1
WORKDIR /chunking-worker
CMD ["python", "-m", "chunking_worker.main"]
