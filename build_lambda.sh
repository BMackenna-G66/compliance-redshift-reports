#!/usr/bin/env bash
# Builds the Lambda deployment package into ./lambda_build/.
# Terraform's archive_file then zips that directory into lambda_package.zip.
#
# Run this before `terraform plan` or `terraform apply` if you've changed code.

set -euo pipefail

cd "$(dirname "$0")"

BUILD_DIR="lambda_build"

echo "→ Cleaning previous build"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

echo "→ Copying source files"
cp lambda/handler.py "$BUILD_DIR/"
cp lambda/api_handler.py "$BUILD_DIR/"
cp lambda/aml_individual.py "$BUILD_DIR/"
cp lambda/email_template.html "$BUILD_DIR/"
mkdir -p "$BUILD_DIR/queries" "$BUILD_DIR/config"
cp lambda/queries/*.sql "$BUILD_DIR/queries/"
cp config/*.yaml "$BUILD_DIR/config/"

echo "→ Installing Python dependencies for Linux/x86_64 (Lambda runtime)"
# --platform / --only-binary forces wheels compatible with the Lambda runtime.
pip install \
  --target "$BUILD_DIR" \
  --requirement lambda/requirements.txt \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  --upgrade \
  --quiet

# Trim deps to reduce package size (optional)
find "$BUILD_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true

echo "→ Build complete: $(du -sh "$BUILD_DIR" | cut -f1)"
echo "→ Ready for: cd infra && terraform apply"
