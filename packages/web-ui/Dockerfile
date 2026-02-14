# Web UI: FastAPI + Jinja2, served with uvicorn.
# Build from repo root: docker build -f packages/web-ui/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

# Monorepo: copy and install shared-types and aws-adapters first
COPY packages/shared-types /shared-types
COPY packages/aws-adapters /aws-adapters
RUN pip install --no-cache-dir -e /shared-types -e /aws-adapters

COPY packages/web-ui /web-ui
RUN pip install --no-cache-dir -e /web-ui

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
WORKDIR /web-ui
CMD ["uvicorn", "stereo_spot_web_ui.main:app", "--host", "0.0.0.0", "--port", "8000"]
