# Job worker: consumes job-status-events queue, writes SegmentCompletions, updates job status, triggers reassembly.
# Build from repo root: docker build -f packages/job-worker/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

# Monorepo: copy and install shared-types, adapters, aws-adapters, video-worker first
COPY packages/shared-types /shared-types
COPY packages/adapters /adapters
COPY packages/aws-adapters /aws-adapters
COPY packages/video-worker /video-worker
RUN pip install --no-cache-dir -e /shared-types -e /adapters -e /aws-adapters -e /video-worker

COPY packages/job-worker /job-worker
RUN pip install --no-cache-dir -e /job-worker

ENV PYTHONUNBUFFERED=1
WORKDIR /job-worker
CMD ["python", "-m", "job_worker.main"]
