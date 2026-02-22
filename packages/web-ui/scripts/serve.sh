#!/usr/bin/env bash
# Run from repo root (e.g. nx run web-ui:serve). Copies 3D Linker EXE into static, then starts uvicorn.
set -e

STATIC_DIR="packages/web-ui/src/stereo_spot_web_ui/static"
EXE_SRC="packages/desktop-launcher-setup/dist/3d_setup.exe"
EXE_DST="${STATIC_DIR}/3d_setup.exe"

mkdir -p "$STATIC_DIR"
if [[ -f "$EXE_SRC" ]]; then
  cp "$EXE_SRC" "$EXE_DST"
fi

export STEREOSPOT_ENV_FILE="${PWD}/packages/aws-infra/.env"
cd packages/web-ui && exec uvicorn stereo_spot_web_ui.main:app --reload
