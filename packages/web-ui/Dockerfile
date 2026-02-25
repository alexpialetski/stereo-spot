# Web UI: FastAPI + Jinja2, served with uvicorn.
# Build from repo root: docker build -f packages/web-ui/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

# Monorepo: copy and install shared-types, adapters, aws-adapters first
COPY packages/shared-types /shared-types
COPY packages/adapters /adapters
COPY packages/aws-adapters /aws-adapters
RUN pip install --no-cache-dir -e /shared-types -e /adapters -e /aws-adapters

COPY packages/web-ui /web-ui
# 3D Linker setup EXE (built by desktop-launcher-setup:build before this image)
COPY packages/desktop-launcher-setup/dist/3d_setup.exe /web-ui/src/stereo_spot_web_ui/static/3d_setup.exe
RUN pip install --no-cache-dir -e /web-ui

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
WORKDIR /web-ui
CMD ["uvicorn", "stereo_spot_web_ui.main:app", "--host", "0.0.0.0", "--port", "8000"]
