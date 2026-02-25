# Video worker: consumes video-worker queue, runs inference (stub or model), uploads output, writes SegmentCompletion.
# Build from repo root: docker build -f packages/video-worker/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

# Monorepo: copy and install shared-types, adapters, aws-adapters first
COPY packages/shared-types /shared-types
COPY packages/adapters /adapters
COPY packages/aws-adapters /aws-adapters
RUN pip install --no-cache-dir -e /shared-types -e /adapters -e /aws-adapters

COPY packages/video-worker /video-worker
RUN pip install --no-cache-dir -e /video-worker

ENV PYTHONUNBUFFERED=1
WORKDIR /video-worker
CMD ["python", "-m", "video_worker.main"]
