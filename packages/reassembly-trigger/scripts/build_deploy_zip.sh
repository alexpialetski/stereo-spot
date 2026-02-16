#!/usr/bin/env bash
# Build Lambda deployment zip: shared-types wheel (with deps, e.g. pydantic) + reassembly_trigger code.
# Run from repo root. Requires: shared-types built (nx run shared-types:build),
# Docker (to install for Lambda's platform) or pip+zip.
# Lambda uses python3.12; pydantic_core is a native extension and must be built for Linux x86_64.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(cd "${PKG_DIR}/../.." && pwd)"
SHARED_DIST="${PKG_DIR}/../shared-types/dist"
OUT_DIR="${PKG_DIR}/dist"
STAGING="${OUT_DIR}/lambda_staging"
ZIP_PATH="${OUT_DIR}/deploy.zip"
# AWS Lambda base image: python with tag 3.12 (not python3.12)
LAMBDA_IMAGE="public.ecr.aws/lambda/python:3.12"

WHEEL=""
for w in "${SHARED_DIST}"/stereo_spot_shared-*.whl; do
  [ -f "$w" ] && WHEEL="$w" && break
done
if [ -z "$WHEEL" ]; then
  echo "Shared-types wheel not found in ${SHARED_DIST}. Run: nx run shared-types:build"
  exit 1
fi

# Prefer Docker so pydantic_core and other native deps are built for Lambda (Linux x86_64).
# Docker does install, zip, and cleanup so root-owned files are never left on the host.
if command -v docker &>/dev/null; then
  WHEEL_BASENAME="$(basename "$WHEEL")"
  mkdir -p "$OUT_DIR"
  docker run --rm --entrypoint "" \
    -v "${REPO_ROOT}:/workspace" \
    -w /workspace \
    "${LAMBDA_IMAGE}" \
    bash -c 'set -e
      STAGING=/workspace/packages/reassembly-trigger/dist/lambda_staging
      ZIP_PATH=/workspace/packages/reassembly-trigger/dist/deploy.zip
      rm -rf "$STAGING"
      mkdir -p "$STAGING"
      pip install /workspace/packages/shared-types/dist/'"${WHEEL_BASENAME}"' -t "$STAGING" -q
      cp -r /workspace/packages/reassembly-trigger/src/reassembly_trigger "$STAGING/"
      export STAGING ZIP_PATH
      python3 -c "
import zipfile, os
with zipfile.ZipFile(os.environ[\"ZIP_PATH\"], \"w\", zipfile.ZIP_DEFLATED) as zf:
    for r, ds, fs in os.walk(os.environ[\"STAGING\"]):
        for f in fs:
            p = os.path.join(r, f)
            zf.write(p, os.path.relpath(p, os.environ[\"STAGING\"]))
"
      rm -rf "$STAGING"'
else
  rm -rf "$STAGING"
  mkdir -p "$STAGING"
  pip install --no-deps "$WHEEL" -t "$STAGING" --quiet
  pip install pydantic -t "$STAGING" --quiet \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all:
  cp -r "${PKG_DIR}/src/reassembly_trigger" "$STAGING/"
  cd "$STAGING" && zip -r -q "$ZIP_PATH" . && cd - > /dev/null
  rm -rf "$STAGING"
fi
echo "Built $ZIP_PATH"
