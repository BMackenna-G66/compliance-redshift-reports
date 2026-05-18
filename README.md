# compliance-redshift-reports

Automated AML/sanctions screening reports over Redshift. Pulls transactions to high-risk
jurisdictions on a schedule, generates an Excel + HTML report, and delivers it via
email (SES) and Slack.

Built to run cheap, only resuming the Redshift cluster while the query runs.

## Architecture (MVP)

```
EventBridge (cron 08:00 UTC Mon-Fri)
        │
        ▼
   Lambda  ──► Redshift Data API
   handler                    │
        │   1. Resume cluster (if paused)
        │   2. Wait until available
        │   3. Execute parameterized SQL
        │   4. Fetch results
        │   5. Build Excel (.xlsx) + HTML body
        │   6. Upload .xlsx to S3 (SSE-encrypted)
        │   7. Send SES email with attachment + presigned link
        │   8. POST summary to Slack webhook
        │   9. Pause cluster
        ▼
   CloudWatch Logs (audit trail)
```

Single Lambda for the MVP. When you outgrow the 15-minute Lambda timeout or want
parallel reports, we split it into Step Functions (already designed, just not yet
implemented).

## Repo layout

```
.
├── README.md               this file
├── DEPLOY.md               step-by-step deployment guide — read this next
├── .gitignore
├── queries/
│   └── high_risk_countries_transactions.sql
├── config/
│   └── high_risk_countries.yaml
├── lambda/
│   ├── handler.py
│   ├── email_template.html
│   └── requirements.txt
└── infra/
    ├── main.tf
    ├── variables.tf
    ├── outputs.tf
    └── terraform.tfvars.example
```

## Stack

- **AWS Lambda** (Python 3.12) — orchestration + report generation
- **Redshift Data API** — async SQL execution, no VPC required
- **EventBridge Scheduler** — cron trigger
- **S3** — report storage (SSE-S3 encryption, 90-day lifecycle)
- **SES** — email delivery
- **Secrets Manager** — Slack webhook URL
- **CloudWatch Logs** — execution logs
- **Terraform** — IaC

## What runs today

One report: **High-risk countries transactions** (FATF + sanctions watchlist).
Pulls outbound transactions to ~50 jurisdictions since a configurable start date.

Default schedule: every Monday at 08:00 UTC. Parameters can be overridden via manual
Lambda invocation.

## Quickstart

Read [DEPLOY.md](./DEPLOY.md). Roughly:

```bash
# 1. Configure terraform.tfvars from the example
cd infra
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars with your account-specific values

# 2. Deploy
terraform init
terraform plan
terraform apply

# 3. Test
aws lambda invoke \
  --function-name compliance-redshift-reports \
  --payload '{"since_date": "2026-04-25"}' \
  --cli-binary-format raw-in-base64-out \
  response.json
```

## Roadmap

- [x] **Phase 1** — Single-report Lambda, EventBridge schedule, SES + Slack
- [ ] **Phase 2** — Multi-report catalog, SQL files with YAML metadata, dynamic params
- [ ] **Phase 3** — Static frontend (Amplify) with form-based triggering
- [ ] **Phase 4** — Redshift ML for anomaly detection + Bedrock Claude for narrative analysis
- [ ] **Phase 5** — Step Functions orchestration, multi-tenant reports

## Cost estimate

- Lambda: <$2/mo
- S3: <$1/mo
- SES: $0.10 per 1000 emails
- Secrets Manager: $0.40/mo per secret
- CloudWatch Logs: <$1/mo
- Redshift: no extra cost beyond what you already pay (cluster only resumes during runs)

**Total new infra: ~$5/mo.**
