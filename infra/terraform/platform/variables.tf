variable "project_name" {
  description = "Project name used in resource names and tags."
  type        = string
  default     = "research-data-builder"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,31}$", var.project_name))
    error_message = "The project name must use 3 through 32 lowercase letters, numbers, or hyphens."
  }
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "The environment must be dev, staging, or production."
  }
}

variable "aws_region" {
  description = "AWS region for application resources."
  type        = string
  default     = "eu-central-1"
}

variable "vpc_cidr" {
  description = "IPv4 CIDR block for the application VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "single_nat_gateway" {
  description = "Use one NAT gateway in dev to reduce cost. Production requires one gateway in each availability zone."
  type        = bool
  default     = true
}

variable "database_name" {
  description = "Initial PostgreSQL database name."
  type        = string
  default     = "research_data"
}

variable "database_username" {
  description = "PostgreSQL administrator user. RDS manages its password."
  type        = string
  default     = "research_admin"
}

variable "database_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "database_allocated_storage" {
  description = "Initial RDS storage in GiB."
  type        = number
  default     = 20
}

variable "database_max_allocated_storage" {
  description = "Maximum RDS autoscaled storage in GiB."
  type        = number
  default     = 100
}

variable "database_backup_retention_days" {
  description = "Number of days that RDS keeps automated backups."
  type        = number
  default     = 7
}

variable "database_multi_az" {
  description = "Create a standby RDS instance in another availability zone."
  type        = bool
  default     = false
}

variable "database_deletion_protection" {
  description = "Block deletion of the RDS instance."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Additional tags for all AWS resources."
  type        = map(string)
  default     = {}
}
