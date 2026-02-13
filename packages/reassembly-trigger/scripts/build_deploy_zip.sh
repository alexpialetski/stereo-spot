#!/usr/bin/env bash
# Build Lambda deployment zip: shared-types wheel + reassembly_trigger code.
# Run from repo root. Requires: shared-types built (nx run shared-types:build),
# pip, zip.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(dirname "$SCRIPT_DIR")"
SHARED_DIST="${PKG_DIR}/../shared-types/dist"
OUT_DIR="${PKG_DIR}/dist"
STAGING="${OUT_DIR}/lambda_staging"
ZIP_PATH="${OUT_DIR}/deploy.zip"

WHEEL=""
for w in "${SHARED_DIST}"/stereo_spot_shared-*.whl; do
  [ -f "$w" ] && WHEEL="$w" && break
done
if [ -z "$WHEEL" ]; then
  echo "Shared-types wheel not found in ${SHARED_DIST}. Run: nx run shared-types:build"
  exit 1
fi

rm -rf "$STAGING"
mkdir -p "$STAGING"
pip install --no-deps "$WHEEL" -t "$STAGING" --quiet
cp -r "${PKG_DIR}/src/reassembly_trigger" "$STAGING/"
cd "$STAGING" && zip -r -q "$ZIP_PATH" . && cd - > /dev/null
rm -rf "$STAGING"
echo "Built $ZIP_PATH"
