#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

SRC_DIR="${REPO_ROOT}/src/lambdas/rag"
TF_MODULE_DIR="${REPO_ROOT}/infrastructure/modules/lambda/rag_query"

REQ_FILE="${SRC_DIR}/requirements.txt"
PY_FILE="${SRC_DIR}/rag_query_lambda.py"

OUT_ZIP="${TF_MODULE_DIR}/lambda_package.zip"
BUILD_DIR="${TF_MODULE_DIR}/.build"

[[ -f "${REQ_FILE}" ]] || { echo "Missing: ${REQ_FILE}"; exit 1; }
[[ -f "${PY_FILE}"  ]] || { echo "Missing: ${PY_FILE}"; exit 1; }

echo "Cleaning build dir..."
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

echo "Installing dependencies into build dir..."
python3 -m pip install --upgrade pip >/dev/null

python3 -m pip install \
  --no-cache-dir \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 311 \
  --only-binary=:all: \
  -r "${REQ_FILE}" \
  -t "${BUILD_DIR}"

echo "Copying lambda code..."
cp "${PY_FILE}" "${BUILD_DIR}/lambda_function.py"

echo "Creating zip..."
rm -f "${OUT_ZIP}"
(
  cd "${BUILD_DIR}"
  python3 -m zipfile -c "${OUT_ZIP}" .
)

echo "Done."
ls -lh "${OUT_ZIP}"
