output "vpc_id" {
  description = "Application VPC ID."
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "Private subnet IDs for ECS tasks."
  value       = [for subnet in aws_subnet.private : subnet.id]
}

output "application_security_group_id" {
  description = "Security group ID for ECS tasks."
  value       = aws_security_group.application.id
}

output "api_repository_url" {
  description = "ECR repository URL for the API image."
  value       = aws_ecr_repository.api.repository_url
}

output "worker_repository_url" {
  description = "ECR repository URL for the worker image."
  value       = aws_ecr_repository.worker.repository_url
}

output "database_endpoint" {
  description = "Private RDS PostgreSQL endpoint."
  value       = aws_db_instance.main.address
}

output "database_master_secret_arn" {
  description = "RDS-managed secret ARN for the database administrator."
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
  sensitive   = true
}

output "build_queue_url" {
  description = "SQS build queue URL."
  value       = aws_sqs_queue.build.url
}

output "build_dead_letter_queue_url" {
  description = "SQS dead-letter queue URL."
  value       = aws_sqs_queue.build_dead_letter.url
}

output "artifact_bucket_name" {
  description = "Private S3 artifact bucket name."
  value       = aws_s3_bucket.artifacts.id
}

output "fred_api_key_secret_arn" {
  description = "Secret ARN that will contain the FRED API key."
  value       = aws_secretsmanager_secret.fred_api_key.arn
}
