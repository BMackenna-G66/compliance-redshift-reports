# =============================================================================
# Google as a Federated Identity Provider for Cognito
#
# Prerequisites:
#   1. Create a Google OAuth 2.0 Client in the Google Cloud Console:
#      https://console.cloud.google.com/apis/credentials
#      - Authorized redirect URI:
#        https://<cognito-domain>.auth.us-east-1.amazoncognito.com/oauth2/idpresponse
#
#   2. Set the variables in terraform.tfvars (or via environment variables):
#        google_client_id     = "<your-google-client-id>"
#        google_client_secret = "<your-google-client-secret>"
#
#   3. After applying this file, also update frontend.tf manually:
#      In the aws_cognito_user_pool_client.frontend resource, change:
#        supported_identity_providers = ["COGNITO"]
#      to:
#        supported_identity_providers = compact(["COGNITO", var.google_client_id != "" ? "Google" : ""])
#      This ensures the hosted UI shows the "Sign in with Google" button.
#
# To skip Google IdP entirely, leave google_client_id empty (default = "").
# =============================================================================

resource "aws_cognito_identity_provider" "google" {
  count = var.google_client_id != "" ? 1 : 0

  user_pool_id  = aws_cognito_user_pool.main.id
  provider_name = "Google"
  provider_type = "Google"

  provider_details = {
    client_id        = var.google_client_id
    client_secret    = var.google_client_secret
    authorize_scopes = "email openid profile"
  }

  attribute_mapping = {
    email    = "email"
    name     = "name"
    username = "sub"
  }
}
