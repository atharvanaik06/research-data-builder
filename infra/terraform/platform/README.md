# AWS Platform Foundation

This Terraform configuration creates the first Phase 8 infrastructure unit:

- one VPC across two availability zones.
- public subnets for a later load balancer.
- private subnets for later ECS tasks.
- isolated database subnets.
- one development NAT gateway or one production gateway in each availability zone.
- two encrypted ECR repositories.
- one private and encrypted RDS PostgreSQL instance.
- one encrypted S3 artifact bucket.
- one encrypted SQS build queue and dead-letter queue.
- one KMS key.
- one empty Secrets Manager record for the FRED API key.

The configuration does not create ECS services or a load balancer yet. The next Phase 8 unit will add them.

## Before the first plan

1. Apply the bootstrap configuration.
2. Copy `backend.hcl.example` to `backend.hcl`.
3. Enter the real state bucket name.
4. Copy `terraform.tfvars.example` to `terraform.tfvars`.
5. Review the database size and protection settings.

```bash
terraform init -backend-config=backend.hcl
terraform plan
```

Do not run `terraform apply` until you review the plan and estimated AWS cost. The NAT gateway and RDS instance create continuous charges.

Do not put the FRED key in Terraform. After the platform exists, add the key directly to the created Secrets Manager record.
