# =============================================================================
# Fase 3 — Frontend + API infrastructure
#
# Resources created here:
#   - DynamoDB: runs table + catalog table
#   - Cognito: User Pool + Client + Domain
#   - API Lambda (api_handler.py) + IAM role
#   - API Gateway HTTP API + JWT authorizer + $default route
#   - Frontend S3 bucket (private) + CloudFront OAC + distribution
#   - S3 objects: index.html + config.json
# =============================================================================

# ---------------------------------------------------------------------------
# DynamoDB — run history
# ---------------------------------------------------------------------------
resource "aws_dynamodb_table" "runs" {
  name         = "${var.project_name}-runs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"

  attribute {
    name = "run_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

# ---------------------------------------------------------------------------
# DynamoDB — custom query catalog
# ---------------------------------------------------------------------------
resource "aws_dynamodb_table" "catalog" {
  name         = "${var.project_name}-catalog"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "report_name"

  attribute {
    name = "report_name"
    type = "S"
  }
}

# ---------------------------------------------------------------------------
# DynamoDB — whitelist
# ---------------------------------------------------------------------------
resource "aws_dynamodb_table" "whitelist" {
  name         = "${var.project_name}-whitelist"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "whitelist_id"

  attribute {
    name = "whitelist_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

# ---------------------------------------------------------------------------
# DynamoDB — alerts (alertados + ya revisados via status field)
# ---------------------------------------------------------------------------
resource "aws_dynamodb_table" "alerts" {
  name         = "${var.project_name}-alerts"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "alert_id"

  attribute {
    name = "alert_id"
    type = "S"
  }
}

# ---------------------------------------------------------------------------
# Cognito User Pool
# ---------------------------------------------------------------------------
resource "aws_cognito_user_pool" "main" {
  name = "${var.project_name}-users"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_numbers   = true
    require_symbols   = false
    require_uppercase = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  admin_create_user_config {
    allow_admin_create_user_only = true
  }
}

# ---------------------------------------------------------------------------
# Cognito User Pool Client (PKCE — no secret, code flow)
# Callback URL uses CloudFront domain → computed after distribution is known
# ---------------------------------------------------------------------------
resource "aws_cognito_user_pool_client" "frontend" {
  name         = "${var.project_name}-frontend"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]

  callback_urls = ["https://${aws_cloudfront_distribution.frontend.domain_name}"]
  logout_urls   = ["https://${aws_cloudfront_distribution.frontend.domain_name}"]

  supported_identity_providers = compact(["COGNITO", var.google_client_id != "" ? "Google" : ""])

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  # Token validity
  access_token_validity  = 1    # hours
  id_token_validity      = 1    # hours
  refresh_token_validity = 30   # days

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}

# ---------------------------------------------------------------------------
# Cognito User Pool Domain (globally unique — uses account ID as suffix)
# ---------------------------------------------------------------------------
resource "aws_cognito_user_pool_domain" "main" {
  domain       = "${var.project_name}-${var.aws_account_id}"
  user_pool_id = aws_cognito_user_pool.main.id
}

# ---------------------------------------------------------------------------
# IAM role for the API Lambda
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "api_lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api_lambda" {
  name               = "${var.project_name}-api-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.api_lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "api_lambda_basic" {
  role       = aws_iam_role.api_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "api_lambda_inline" {
  statement {
    sid    = "DynamoDB"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:GetItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Scan",
      "dynamodb:Query",
    ]
    resources = [
      aws_dynamodb_table.runs.arn,
      aws_dynamodb_table.catalog.arn,
      aws_dynamodb_table.whitelist.arn,
      aws_dynamodb_table.alerts.arn,
    ]
  }

  statement {
    sid       = "InvokeReportLambda"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.report.arn]
  }

  statement {
    sid     = "S3Presign"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.reports.arn}/*"]
  }
}

resource "aws_iam_role_policy" "api_lambda_inline" {
  name   = "${var.project_name}-api-lambda-inline"
  role   = aws_iam_role.api_lambda.id
  policy = data.aws_iam_policy_document.api_lambda_inline.json
}

# ---------------------------------------------------------------------------
# API Lambda function
# Same zip as the report Lambda — both handlers live in the same package
# ---------------------------------------------------------------------------
resource "aws_lambda_function" "api" {
  function_name    = "${var.project_name}-api"
  role             = aws_iam_role.api_lambda.arn
  runtime          = "python3.12"
  handler          = "api_handler.handler"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  memory_size      = 512
  timeout          = 30

  environment {
    variables = {
      RUNS_TABLE      = aws_dynamodb_table.runs.name
      CATALOG_TABLE   = aws_dynamodb_table.catalog.name
      REPORT_LAMBDA   = aws_lambda_function.report.function_name
      S3_BUCKET       = aws_s3_bucket.reports.bucket
      WHITELIST_TABLE = aws_dynamodb_table.whitelist.name
      ALERTS_TABLE    = aws_dynamodb_table.alerts.name
    }
  }
}

# ---------------------------------------------------------------------------
# API Gateway HTTP API
# ---------------------------------------------------------------------------
resource "aws_apigatewayv2_api" "main" {
  name          = "${var.project_name}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_credentials = true
    allow_headers     = ["Authorization", "Content-Type"]
    allow_methods     = ["GET", "POST", "DELETE", "OPTIONS"]
    allow_origins     = ["https://${aws_cloudfront_distribution.frontend.domain_name}"]
    max_age           = 300
  }
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.main.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "cognito-jwt"

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.frontend.id]
    issuer   = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
  }
}

resource "aws_apigatewayv2_integration" "api_lambda" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "default" {
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = "$default"
  target             = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# Frontend S3 bucket (private — content served only through CloudFront OAC)
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "frontend" {
  bucket        = "${var.project_name}-frontend-${var.aws_account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------------------------------------------------------------------------
# CloudFront Origin Access Control
# ---------------------------------------------------------------------------
resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = "${var.project_name}-frontend-oac"
  description                       = "OAC for compliance reports frontend"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# ---------------------------------------------------------------------------
# CloudFront distribution
# ---------------------------------------------------------------------------
resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  comment             = "Compliance Reports frontend"

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "frontend-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  # Default: cache aggressively
  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "frontend-s3"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }

    min_ttl     = 0
    default_ttl = 3600
    max_ttl     = 86400
  }

  # config.json: never cache so Terraform updates appear immediately
  ordered_cache_behavior {
    path_pattern           = "/config.json"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "frontend-s3"
    viewer_protocol_policy = "redirect-to-https"
    compress               = false

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# ---------------------------------------------------------------------------
# S3 bucket policy — allow CloudFront OAC to read objects
# ---------------------------------------------------------------------------
resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudFrontOAC"
        Effect = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.frontend.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.frontend.arn
          }
        }
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# Static assets — uploaded by Terraform so a code push is one step
# ---------------------------------------------------------------------------
resource "aws_s3_object" "index_html" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "index.html"
  source       = "${path.module}/../frontend/index.html"
  content_type = "text/html"
  etag         = filemd5("${path.module}/../frontend/index.html")
}

resource "aws_s3_object" "config_json" {
  bucket = aws_s3_bucket.frontend.id
  key    = "config.json"
  content = jsonencode({
    apiUrl        = trimprefix(aws_apigatewayv2_stage.default.invoke_url, "/")
    userPoolId    = aws_cognito_user_pool.main.id
    clientId      = aws_cognito_user_pool_client.frontend.id
    cognitoDomain = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com"
    region        = var.aws_region
  })
  content_type = "application/json"

  # Force re-upload whenever any output value changes (e.g., new API URL)
  etag = md5(jsonencode({
    apiUrl        = trimprefix(aws_apigatewayv2_stage.default.invoke_url, "/")
    userPoolId    = aws_cognito_user_pool.main.id
    clientId      = aws_cognito_user_pool_client.frontend.id
    cognitoDomain = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com"
    region        = var.aws_region
  }))
}
