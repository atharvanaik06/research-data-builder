resource "aws_kms_key" "main" {
  description             = "Research Data Builder ${var.environment} data key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "main" {
  name          = "alias/${local.name_prefix}"
  target_key_id = aws_kms_key.main.key_id
}

resource "aws_security_group" "application" {
  name        = "${local.name_prefix}-application"
  description = "ECS API and worker tasks"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-application"
  }
}

resource "aws_vpc_security_group_egress_rule" "application_ipv4" {
  security_group_id = aws_security_group.application.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Allow provider and AWS service access"
}

resource "aws_security_group" "database" {
  name        = "${local.name_prefix}-database"
  description = "RDS PostgreSQL access from application tasks"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-database"
  }
}

resource "aws_vpc_security_group_ingress_rule" "database_from_application" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.application.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  description                  = "Allow PostgreSQL from ECS tasks"
}
