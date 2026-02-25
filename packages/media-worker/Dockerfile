# Media worker: chunking (ffmpeg split) + reassembly (ffmpeg concat). One image for both.
# Build from repo root: docker build -f packages/media-worker/Dockerfile .

# Stage 1: build Deno binary for yt-dlp EJS (YouTube n challenge solver)
FROM python:3.12-slim AS deno-builder
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://deno.land/install.sh | sh -s v2.6.10 \
    && mv /root/.deno/bin/deno /usr/local/bin/deno \
    && rm -rf /root/.deno

# Stage 2: runtime image
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=deno-builder /usr/local/bin/deno /usr/local/bin/deno

WORKDIR /app

# Monorepo: copy and install shared-types, adapters, aws-adapters first
COPY packages/shared-types /shared-types
COPY packages/adapters /adapters
COPY packages/aws-adapters /aws-adapters
RUN pip install --no-cache-dir -e /shared-types -e /adapters -e /aws-adapters

COPY packages/media-worker /media-worker
RUN pip install --no-cache-dir -e /media-worker

ENV PYTHONUNBUFFERED=1
WORKDIR /media-worker
CMD ["python", "-m", "media_worker.main"]
