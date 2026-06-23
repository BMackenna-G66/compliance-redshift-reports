output "frontend_url" {
  value       = "https://${aws_cloudfront_distribution.frontend.domain_name}"
  description = "URL of the compliance reports frontend"
}

output "api_url" {
  value       = aws_apigatewayv2_stage.default.invoke_url
  description = "Base URL for the compliance reports API"
}

output "cognito_user_pool_id" {
  value       = aws_cognito_user_pool.main.id
  description = "Cognito User Pool ID — needed for CLI user management"
}

output "cognito_client_id" {
  value       = aws_cognito_user_pool_client.frontend.id
  description = "Cognito App Client ID used by the frontend"
}

output "cognito_domain" {
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${var.aws_region}.amazoncognito.com"
  description = "Cognito hosted UI base URL"
}

output "add_user_command" {
  value       = <<-EOT
    # Create the first Compliance user:
    aws cognito-idp admin-create-user \
      --user-pool-id ${aws_cognito_user_pool.main.id} \
      --username benjamin.mackenna@global66.com \
      --user-attributes Name=email,Value=benjamin.mackenna@global66.com Name=email_verified,Value=true \
      --temporary-password "Compliance2026!" \
      --region ${var.aws_region} \
      --profile compliance-admin
  EOT
  description = "Run this after apply to create the first frontend user"
}
