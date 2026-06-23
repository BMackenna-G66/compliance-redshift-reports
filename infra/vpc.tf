# =============================================================================
# VPC — WatchTower CRM V2 (Phase 0)
#
# References the existing Compliance-vpc instead of creating a new one.
# The existing VPC already has:
#   - Private subnets in 2 AZs with NAT Gateway routing
#   - Public subnets with Internet Gateway
#   - NAT Gateway (nat-1d14ecf7896f558dc) available
#
# New resources created here (require ec2:CreateSecurityGroup permission):
#   - aws_security_group.lambda  — outbound-only for Lambda
#   - aws_security_group.rds     — MySQL inbound from Lambda SG only
# =============================================================================

# ---------------------------------------------------------------------------
# Reference existing VPC and subnets (read-only data sources)
# ---------------------------------------------------------------------------
data "aws_vpc" "main" {
  id = "vpc-0c505d3b18a721212"
}

data "aws_subnet" "private" {
  count = 2
  id = [
    "subnet-04ab473667df77ebc", # Compliance-subnet-private1-us-east-1a
    "subnet-029ef8e87cca25deb", # Compliance-subnet-private2-us-east-1b
  ][count.index]
}

# ---------------------------------------------------------------------------
# Security Groups
# NOTE: These require ec2:CreateSecurityGroup permission.
# Add AmazonVPCFullAccess (or a scoped EC2 policy) to your IAM Identity
# Center permission set, then re-run terraform apply.
# ---------------------------------------------------------------------------
resource "aws_security_group" "lambda" {
  name        = "${var.project_name}-lambda-sg"
  description = "API Lambda — full outbound, no inbound (API Gateway proxies in)"
  vpc_id      = data.aws_vpc.main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound via NAT Gateway"
  }

  tags = { Name = "${var.project_name}-lambda-sg" }
}

resource "aws_security_group" "rds" {
  name        = "${var.project_name}-rds-sg"
  description = "RDS MySQL — MySQL inbound from Lambda SG only"
  vpc_id      = data.aws_vpc.main.id

  ingress {
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id]
    description     = "MySQL from Lambda"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-rds-sg" }
}
