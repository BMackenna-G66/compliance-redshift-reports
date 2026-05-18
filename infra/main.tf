terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}

# ---------------------------------------------------------------------------
# Data source — sanity check that the cluster exists in this account/region
# ---------------------------------------------------------------------------
data "aws_redshift_cluster" "target" {
  cluster_identifier = var.redshift_cluster_identifier
}

# ---------------------------------------------------------------------------
# S3 bucket for report outputs
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "reports" {
  bucket        = var.s3_bucket_name
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "reports" {
  bucket                  = aws_s3_bucket.reports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "reports" {
  bucket = aws_s3_bucket.reports.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id
  rule {
    id     = "expire-old-reports"
    status = "Enabled"
    filter {}
    expiration {
      days = 90
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# ---------------------------------------------------------------------------
# Secrets Manager — Slack webhook URL
# ---------------------------------------------------------------------------
resource "aws_secretsmanager_secret" "slack_webhook" {
  name                    = "${var.project_name}/slack-webhook"
  description             = "Incoming webhook URL for compliance reports notifications"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "slack_webhook" {
  secret_id     = aws_secretsmanager_secret.slack_webhook.id
  secret_string = var.slack_webhook_url
}

# ---------------------------------------------------------------------------
# IAM role for Lambda
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.project_name}-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "lambda_inline" {
  # Redshift cluster control + IAM auth
  statement {
    sid    = "RedshiftClusterControl"
    effect = "Allow"
    actions = [
      "redshift:DescribeClusters",
      "redshift:PauseCluster",
      "redshift:ResumeCluster",
      "redshift:GetClusterCredentials",
    ]
    resources = [
      "arn:aws:redshift:${var.aws_region}:${var.aws_account_id}:cluster:${var.redshift_cluster_identifier}",
      "arn:aws:redshift:${var.aws_region}:${var.aws_account_id}:dbuser:${var.redshift_cluster_identifier}/${var.redshift_db_user}",
      "arn:aws:redshift:${var.aws_region}:${var.aws_account_id}:dbname:${var.redshift_cluster_identifier}/${var.redshift_database}",
    ]
  }

  # Redshift Data API — uses * because Data API actions are not resource-scoped
  statement {
    sid    = "RedshiftDataAPI"
    effect = "Allow"
    actions = [
      "redshift-data:ExecuteStatement",
      "redshift-data:DescribeStatement",
      "redshift-data:GetStatementResult",
      "redshift-data:CancelStatement",
      "redshift-data:ListStatements",
    ]
    resources = ["*"]
  }

  # S3 — only the reports bucket
  statement {
    sid    = "S3Reports"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.reports.arn,
      "${aws_s3_bucket.reports.arn}/*",
    ]
  }

  # SES
  statement {
    sid    = "SES"
    effect = "Allow"
    actions = [
      "ses:SendEmail",
      "ses:SendRawEmail",
    ]
    resources = ["*"]
  }

  # Secrets Manager — Slack webhook only
  statement {
    sid       = "SlackSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.slack_webhook.arn]
  }
}

resource "aws_iam_role_policy" "lambda_inline" {
  name   = "${var.project_name}-lambda-inline"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_inline.json
}

# ---------------------------------------------------------------------------
# Lambda layer with Python deps (built locally — see DEPLOY.md)
# ---------------------------------------------------------------------------
# Expects you to have run `./build_lambda.sh` which produces lambda_package.zip
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda_build"
  output_path = "${path.module}/../lambda_package.zip"
}

# ---------------------------------------------------------------------------
# Lambda function
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.project_name}"
  retention_in_days = 90
}

resource "aws_lambda_function" "report" {
  function_name    = var.project_name
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  memory_size      = var.lambda_memory_mb
  timeout          = var.lambda_timeout_seconds

  environment {
    variables = {
      CLUSTER_IDENTIFIER       = var.redshift_cluster_identifier
      DATABASE_NAME            = var.redshift_database
      DB_USER                  = var.redshift_db_user
      S3_BUCKET                = aws_s3_bucket.reports.bucket
      SES_FROM_ADDRESS         = var.ses_from_address
      SES_TO_ADDRESSES         = var.ses_to_addresses
      SLACK_WEBHOOK_SECRET_ARN = aws_secretsmanager_secret.slack_webhook.arn
      REPORT_NAME              = "high_risk_countries"
      AUTO_PAUSE               = tostring(var.auto_pause_cluster)
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}

# ---------------------------------------------------------------------------
# EventBridge schedule
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "${var.project_name}-schedule"
  description         = "Triggers the compliance report on schedule"
  schedule_expression = var.schedule_expression
}

resource "aws_cloudwatch_event_target" "lambda" {
  rule      = aws_cloudwatch_event_rule.schedule.name
  target_id = "lambda"
  arn       = aws_lambda_function.report.arn
}

resource "aws_lambda_permission" "allow_events" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.report.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}
