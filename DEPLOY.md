# Deployment guide

End-to-end deployment of the compliance reports pipeline. Should take you 30–45 min
the first time.

## Prerequisites

On your machine:

- [ ] **AWS CLI v2** configured with credentials that can assume the
  `compliance_admin` role in account `561521480266`
- [ ] **Terraform** ≥ 1.5 ([install](https://developer.hashicorp.com/terraform/install))
- [ ] **Python 3.12** with `pip`
- [ ] **Git** + a GitHub account (`benjamin.mackenna@global66.com` is fine)
- [ ] **GitHub CLI** (`gh`) — optional but handy: `brew install gh`

## Step 1 — Create the GitHub repo

```bash
cd compliance-redshift-reports
git init
git add .
git commit -m "Initial scaffold: AML high-risk countries report"

# Option A: with gh CLI (recommended)
gh auth login
gh repo create compliance-redshift-reports --private --source=. --push

# Option B: manually
# 1. Create empty repo at https://github.com/new
# 2. git remote add origin git@github.com:<you>/compliance-redshift-reports.git
# 3. git branch -M main && git push -u origin main
```

## Step 2 — Configure AWS credentials

Get a session for the `compliance_admin` role:

```bash
# Via IAM Identity Center (the URL you shared):
# https://d-9067bd06cb.awsapps.com/start/#/console?account_id=561521480266&role_name=compliance_admin
# Click "Access keys", export to your terminal, or configure aws sso:

aws configure sso
# SSO start URL: https://d-9067bd06cb.awsapps.com/start
# SSO Region:    us-east-1
# Account ID:    561521480266
# Role:          compliance_admin
# CLI default region: us-east-1

aws sso login --profile compliance-admin
export AWS_PROFILE=compliance-admin

# Sanity check
aws sts get-caller-identity
# Should show account 561521480266
```

## Step 3 — Verify SES sender + recipients

The account is likely in SES sandbox, which means you must verify each address before
sending to or from it.

```bash
aws ses verify-email-identity --email-address benjamin.mackenna@global66.com
```

Then check your inbox and click the verification link from AWS. If you want emails to
go to other people, verify each address too (or request production access for SES later).

## Step 4 — Create the Slack webhook

1. Go to <https://api.slack.com/apps> → **Create New App** → **From scratch**
2. Name: `Compliance Reports Bot`, workspace: Global66
3. Left menu → **Incoming Webhooks** → toggle **On**
4. **Add New Webhook to Workspace** → pick the channel (suggested: `#compliance-reports`)
5. Copy the webhook URL (looks like `https://hooks.slack.com/services/T.../B.../...`)
6. Paste it into `infra/terraform.tfvars` (next step). It will be stored in AWS Secrets Manager, not in code.

## Step 5 — Fill in terraform.tfvars

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars and replace the placeholders for:
#   - slack_webhook_url
#   - ses_from_address (if different)
#   - ses_to_addresses
```

Note: `terraform.tfvars` is in `.gitignore` and **must never be committed**.

## Step 6 — Build the Lambda package

```bash
cd ..   # back to repo root
chmod +x build_lambda.sh
./build_lambda.sh
```

This installs the Python deps for the Lambda runtime (`manylinux2014_x86_64`) into
`lambda_build/`. You'll see a final line like `Build complete: 12M`.

If you're on Apple Silicon and see wheels failures: that's expected — the `--platform`
flag in the script forces Linux x86_64 wheels, which is what Lambda needs. As long as
the script exits 0, you're good.

## Step 7 — Deploy

```bash
cd infra
terraform init
terraform plan      # review what will be created
terraform apply     # type 'yes' when prompted
```

You should see 15–20 resources created in ~2 minutes. At the end Terraform prints
outputs including a ready-to-paste `test_invoke_command`.

## Step 8 — Test the Lambda manually

Use the command Terraform printed, or run:

```bash
aws lambda invoke \
  --function-name compliance-redshift-reports \
  --payload '{"since_date":"2026-04-25"}' \
  --cli-binary-format raw-in-base64-out \
  --region us-east-1 \
  response.json

cat response.json
```

If `auto_pause_cluster = true`, this will resume your Redshift cluster (~60s),
run the query, send email + Slack, and pause the cluster again. Expect a 2–4 minute
runtime end to end.

Watch the logs in real time:

```bash
aws logs tail /aws/lambda/compliance-redshift-reports --follow --region us-east-1
```

## Step 9 — Verify outputs

- [ ] Email arrived at `ses_to_addresses` with the Excel attached
- [ ] Slack channel received the summary message
- [ ] `aws s3 ls s3://<your-bucket>/high_risk_countries/` shows the .xlsx
- [ ] Cluster is back to `paused` (check in console)

## Updating things later

**Updated the SQL or country list?**

```bash
git commit -am "Updated query"
./build_lambda.sh
cd infra && terraform apply
```

**Changed the schedule?**

Edit `schedule_expression` in `terraform.tfvars` and run `terraform apply`.

**Add a new recipient?**

Add to `ses_to_addresses` and run `terraform apply`. If they're new, verify them in
SES first (Step 3).

## Troubleshooting

**`InvalidClusterState: Cluster is not in available state`**
The Lambda's resume logic might be hitting the timeout. Increase `MAX_WAIT_RESUME_SECONDS`
in `handler.py` or check why the cluster is taking long (usually first resume after
a long pause).

**`AccessDenied: redshift:GetClusterCredentials`**
The role you used to deploy doesn't have permission to create IAM auth credentials on
the cluster. Verify the cluster allows IAM auth and your `compliance_admin` role can
do `iam:PassRole`.

**`MessageRejected: Email address is not verified`**
SES sandbox. Verify the address as in Step 3, or request production access.

**`Statement is too large` from Slack**
Your top-countries list is too long. The handler already trims to 5, but if you have
a million-row report and increase that, hit Slack with a richer message format instead
of plain text.

## What's next

After this MVP is running, the natural next steps (in order):

1. **Add 2–3 more reports** — drop new `.sql` files in `queries/`, add metadata, and
   either trigger via Lambda payload or add new EventBridge rules.
2. **Multi-report dispatcher** — let one Lambda accept a `report_name` param and load
   the right SQL + recipients per report.
3. **Static frontend** in AWS Amplify with a form per report.
4. **Redshift ML + Bedrock** — add anomaly scoring and Claude-generated narrative.

Open a new chat when you want to add any of these.
