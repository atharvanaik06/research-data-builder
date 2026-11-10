variable "project_name" {
  description = "Project name used in AWS resource tags."
  type        = string
  default     = "research-data-builder"
}

variable "aws_region" {
  description = "AWS region that stores the Terraform state."
  type        = string
  default     = "eu-central-1"
}

variable "state_bucket_name" {
  description = "Globally unique S3 bucket name for Terraform state."
  type        = string

  validation {
    condition     = length(var.state_bucket_name) >= 3 && length(var.state_bucket_name) <= 63
    error_message = "The state bucket name must contain 3 through 63 characters."
  }
}
