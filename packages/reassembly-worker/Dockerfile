# Reassembly worker: CPU-only; ffmpeg concat, no GPU.
# Build from repo root: docker build -f packages/reassembly-worker/Dockerfile .
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Monorepo: copy and install shared-types and aws-adapters first
COPY packages/shared-types /shared-types
COPY packages/aws-adapters /aws-adapters
RUN pip install --no-cache-dir -e /shared-types -e /aws-adapters

COPY packages/reassembly-worker /reassembly-worker
RUN pip install --no-cache-dir -e /reassembly-worker

ENV PYTHONUNBUFFERED=1
WORKDIR /reassembly-worker
CMD ["python", "-m", "reassembly_worker.main"]
