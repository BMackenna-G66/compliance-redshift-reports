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
cp lambda/db_mysql.py "$BUILD_DIR/"
cp lambda/db_redshift.py "$BUILD_DIR/"
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
  --no-warn-conflicts \
  --quiet

# Trim deps to reduce package size (optional)
find "$BUILD_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find "$BUILD_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true

echo "→ Build complete: $(du -sh "$BUILD_DIR" | cut -f1)"

echo "→ Zipping from inside build dir (files at zip root for Lambda)"
(cd "$BUILD_DIR" && zip -r ../lambda_package.zip . -q)
echo "→ lambda_package.zip created"
echo "→ Deploy: aws s3 cp lambda_package.zip s3://compliance-redshift-reports-561521480266-us-east-1/ --profile compliance-admin && aws lambda update-function-code --function-name compliance-redshift-reports-api --s3-bucket compliance-redshift-reports-561521480266-us-east-1 --s3-key lambda_package.zip --region us-east-1 --profile compliance-admin"
