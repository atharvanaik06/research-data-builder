resource "aws_secretsmanager_secret" "fred_api_key" {
  name                    = "${local.name_prefix}/fred-api-key"
  description             = "FRED API key for Research Data Builder workers"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = 30
}
