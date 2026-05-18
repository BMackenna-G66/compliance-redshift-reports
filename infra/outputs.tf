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

output "test_invoke_command" {
  value = <<-EOT
    aws lambda invoke \
      --function-name ${aws_lambda_function.report.function_name} \
      --payload '{"since_date":"${formatdate("YYYY-MM-DD", timestamp())}"}' \
      --cli-binary-format raw-in-base64-out \
      --region ${var.aws_region} \
      response.json
  EOT
  description = "Copy/paste to test the Lambda manually"
}
