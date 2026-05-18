variable "aws_region" {
  description = "AWS region where everything is deployed"
  type        = string
  default     = "us-east-1"
}

variable "aws_account_id" {
  description = "AWS account ID (used to scope IAM policies)"
  type        = string
}

variable "project_name" {
  description = "Short name used as a prefix for all resources"
  type        = string
  default     = "compliance-redshift-reports"
}

variable "redshift_cluster_identifier" {
  description = "Redshift cluster identifier"
  type        = string
}

variable "redshift_database" {
  description = "Redshift database name"
  type        = string
  default     = "dev"
}

variable "redshift_db_user" {
  description = "Redshift DB user that the Lambda will authenticate as (via GetClusterCredentials)"
  type        = string
  default     = "awsuser"
}

variable "s3_bucket_name" {
  description = "S3 bucket name for report outputs. Must be globally unique."
  type        = string
}

variable "ses_from_address" {
  description = "Verified SES sender email"
  type        = string
}

variable "ses_to_addresses" {
  description = "Comma-separated list of recipient emails"
  type        = string
}

variable "slack_webhook_url" {
  description = "Incoming webhook URL for Slack notifications. Stored in Secrets Manager."
  type        = string
  sensitive   = true
}

variable "schedule_expression" {
  description = "EventBridge schedule expression. Default = every Monday 08:00 UTC."
  type        = string
  default     = "cron(0 8 ? * MON *)"
}

variable "auto_pause_cluster" {
  description = "If true, the Lambda pauses the cluster after a successful run."
  type        = bool
  default     = true
}

variable "lambda_memory_mb" {
  description = "Lambda memory in MB. Increase if reports are large."
  type        = number
  default     = 1024
}

variable "lambda_timeout_seconds" {
  description = "Lambda timeout. Max 900."
  type        = number
  default     = 900
}

variable "tags" {
  description = "Tags applied to all resources"
  type        = map(string)
  default = {
    Project     = "compliance-redshift-reports"
    Environment = "prod"
    ManagedBy   = "terraform"
    Owner       = "compliance"
  }
}
