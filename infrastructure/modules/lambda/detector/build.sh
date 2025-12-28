#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

SRC_DIR="${REPO_ROOT}/src/lambdas/detector"
TF_MODULE_DIR="${REPO_ROOT}/infrastructure/modules/lambda/detector"

REQ_FILE="${SRC_DIR}/requirements.txt"
PY_FILE="${SRC_DIR}/detector_lambda.py"

OUT_ZIP="${TF_MODULE_DIR}/lambda_package.zip"
BUILD_DIR="${TF_MODULE_DIR}/.build"

[[ -f "${REQ_FILE}" ]] || { echo "Missing: ${REQ_FILE}"; exit 1; }
[[ -f "${PY_FILE}"  ]] || { echo "Missing: ${PY_FILE}"; exit 1; }

echo "Cleaning build dir..."
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

echo "Installing dependencies into build dir..."
python3 -m pip install --upgrade pip >/dev/null

# Build deps for Lambda Python 3.11 (x86_64).
python3 -m pip install \
  --no-cache-dir \
  -r "${REQ_FILE}" \
  -t "${BUILD_DIR}"

echo "Copying Lambda code..."
cp "$SRC_DIR/detector_lambda.py" "$BUILD_DIR/lambda_function.py"
cp -r "$SRC_DIR/core" "$BUILD_DIR/"
cp -r "$SRC_DIR/clients" "$BUILD_DIR/"
cp -r "$SRC_DIR/utils" "$BUILD_DIR/"

echo "Creating zip..."
rm -f "${OUT_ZIP}"
(
  cd "${BUILD_DIR}"
  python3 -m zipfile -c "${OUT_ZIP}" .
)

echo "Done."
ls -lh "${OUT_ZIP}"
