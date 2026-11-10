resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-database"
  subnet_ids = [for subnet in aws_subnet.database : subnet.id]

  tags = {
    Name = "${local.name_prefix}-database"
  }
}

resource "aws_db_instance" "main" {
  identifier = "${local.name_prefix}-postgres"

  engine         = "postgres"
  engine_version = "17"
  instance_class = var.database_instance_class

  db_name  = var.database_name
  username = var.database_username
  port     = 5432

  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.main.arn

  allocated_storage     = var.database_allocated_storage
  max_allocated_storage = var.database_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.main.arn

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false
  multi_az               = var.database_multi_az

  backup_retention_period = var.database_backup_retention_days
  backup_window           = "02:00-03:00"
  maintenance_window      = "sun:03:00-sun:04:00"

  auto_minor_version_upgrade = true
  copy_tags_to_snapshot      = true
  deletion_protection        = var.database_deletion_protection
  skip_final_snapshot        = var.environment != "production"
  final_snapshot_identifier  = "${local.name_prefix}-postgres-final"

  performance_insights_enabled = false

  lifecycle {
    precondition {
      condition     = var.database_max_allocated_storage >= var.database_allocated_storage
      error_message = "Maximum database storage must be greater than or equal to initial storage."
    }

    precondition {
      condition     = var.environment != "production" || var.database_multi_az
      error_message = "Production requires a Multi-AZ database."
    }

    precondition {
      condition     = var.environment != "production" || var.database_deletion_protection
      error_message = "Production requires database deletion protection."
    }
  }
}
