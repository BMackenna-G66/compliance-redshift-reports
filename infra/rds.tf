# =============================================================================
# RDS MySQL — WatchTower CRM operational data (Phase 0)
#
# Stores: users, roles, permissions, audit_log (Phase 0)
# Later: alerts_inbox, cases, kanban, files, etc. (Phase 1+)
# =============================================================================

# ---------------------------------------------------------------------------
# Subnet group — uses private subnets from vpc.tf
# ---------------------------------------------------------------------------
resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-db-subnet-group"
  subnet_ids = data.aws_subnet.private[*].id

  tags = { Name = "${var.project_name}-db-subnet-group" }
}

# ---------------------------------------------------------------------------
# Parameter group — UTF-8 MB4, UTC timezone
# ---------------------------------------------------------------------------
resource "aws_db_parameter_group" "mysql8" {
  name   = "${var.project_name}-mysql8"
  family = "mysql8.0"

  parameter {
    name  = "character_set_server"
    value = "utf8mb4"
  }

  parameter {
    name  = "collation_server"
    value = "utf8mb4_unicode_ci"
  }

  parameter {
    name  = "time_zone"
    value = "UTC"
  }
}

# ---------------------------------------------------------------------------
# RDS MySQL 8.0
# ---------------------------------------------------------------------------
resource "aws_db_instance" "main" {
  identifier        = "${var.project_name}-mysql"
  engine            = "mysql"
  engine_version    = "8.0"
  instance_class    = var.rds_instance_class
  allocated_storage = var.rds_storage_gb
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = "watchtower"
  username = "watchtower_admin"
  password = var.rds_master_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.mysql8.name

  # Keep false until load justifies multi-AZ (~2x cost)
  multi_az            = false
  publicly_accessible = false
  deletion_protection = true

  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.project_name}-mysql-final-snapshot"

  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:30-sun:05:30"

  performance_insights_enabled = true

  tags = { Name = "${var.project_name}-mysql" }
}

# ---------------------------------------------------------------------------
# Secrets Manager — RDS credentials
# Lambda reads this via DB_SECRET_ARN env var
# ---------------------------------------------------------------------------
resource "aws_secretsmanager_secret" "rds_credentials" {
  name                    = "${var.project_name}/rds-credentials"
  description             = "WatchTower CRM MySQL credentials for Lambda"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "rds_credentials" {
  secret_id = aws_secretsmanager_secret.rds_credentials.id
  secret_string = jsonencode({
    host     = aws_db_instance.main.address
    port     = aws_db_instance.main.port
    dbname   = aws_db_instance.main.db_name
    username = aws_db_instance.main.username
    password = var.rds_master_password
  })
}
