output "lambda_function_name" {
  value       = aws_lambda_function.report.function_name
  description = "Invoke this function name to run a report manually"
}

output "lambda_function_arn" {
  value = aws_lambda_function.report.arn
}

output "s3_bucket" {
  value       = aws_s3_bucket.reports.bucket
  description = "Where the generated reports are stored"
}

output "slack_secret_arn" {
  value     = aws_secretsmanager_secret.slack_webhook.arn
  sensitive = true
}

output "schedule_rule_name" {
  value = aws_cloudwatch_event_rule.schedule.name
}

output "log_group" {
  value       = "/aws/lambda/${var.project_name}"
  description = "Tail this log group to debug runs (auto-created by Lambda on first invocation)"
}

output "redshift_cluster_endpoint" {
  value       = data.aws_redshift_cluster.target.endpoint
  description = "Sanity check that the cluster was found"
}

output "rds_endpoint" {
  value       = aws_db_instance.main.address
  description = "RDS MySQL endpoint (private — accessible only from Lambda within VPC)"
}

output "rds_secret_arn" {
  value       = aws_secretsmanager_secret.rds_credentials.arn
  sensitive   = true
  description = "Secrets Manager ARN for RDS credentials (DB_SECRET_ARN Lambda env var)"
}

output "vpc_id" {
  value       = data.aws_vpc.main.id
  description = "VPC where Lambda and RDS live"
}

output "nat_gateway_id" {
  value       = "nat-1d14ecf7896f558dc"
  description = "Existing NAT Gateway used by private subnets"
}

output "test_invoke_command" {
  value       = <<-EOT
    aws lambda invoke \
      --function-name ${aws_lambda_function.report.function_name} \
      --payload '{"since_date":"${formatdate("YYYY-MM-DD", timestamp())}"}' \
      --cli-binary-format raw-in-base64-out \
      --region ${var.aws_region} \
      response.json
  EOT
  description = "Copy/paste to test the Lambda manually"
}
