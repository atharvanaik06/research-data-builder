# AWS Infrastructure

## Current Phase 8 unit

Terraform defines the AWS foundation. No command in the repository creates live resources without an explicit `terraform apply`.

The project uses this foundation as its production reference design. The zero-cost public demo does not apply these resources.

The foundation contains:

- a VPC in two availability zones.
- public subnets for the future load balancer.
- private subnets for future ECS tasks.
- isolated subnets for PostgreSQL.
- NAT gateways for provider access.
- encrypted ECR repositories for the API and worker.
- a private RDS PostgreSQL instance.
- an encrypted S3 artifact bucket.
- an encrypted SQS queue and dead-letter queue.
- a KMS key and Secrets Manager record.

## Repository layout

`infra/terraform/bootstrap` creates the private S3 state bucket.

`infra/terraform/platform` creates the application foundation. Its S3 backend uses state locking to prevent concurrent state changes.

GitHub Actions verifies Terraform formatting and both configurations. These jobs do not need AWS credentials and do not create resources.

## Network design

Only the future load balancer will use public subnets. ECS tasks will use private subnets without public IP addresses. The database subnets have no internet route.

Private ECS tasks need outbound access to FRED, World Bank, ECR, and other AWS services. NAT gateways provide this access. An S3 gateway endpoint keeps artifact traffic on the AWS network.

The development configuration uses one NAT gateway to reduce cost. Production requires one NAT gateway in each availability zone. This rule prevents one availability-zone failure from removing all outbound access.

## Database design

RDS manages the administrator password and stores it in Secrets Manager. Terraform does not accept the password as an input.

The database uses encrypted storage, automated backups, private subnets, and a security group. Only the application security group can connect to PostgreSQL.

Development uses one small database instance. Production requires Multi-AZ mode and deletion protection.

## Storage and queue design

The S3 bucket blocks public access. It uses versioning and KMS encryption. It removes incomplete uploads after seven days and old noncurrent versions after 90 days.

The SQS queue uses long polling and KMS encryption. SQS moves a message to the dead-letter queue after five failed deliveries.

## Cost controls

The development defaults use one NAT gateway, one small RDS instance, and no Multi-AZ standby. NAT gateways and RDS create continuous charges.

Always review the Terraform plan and AWS cost estimate before an apply. Do not create production resources during development tests.

See [AWS Recruiter and Interview Guide](AWS_RECRUITER_GUIDE.md) for an honest explanation of the design and its trade-offs.

See [Zero-Cost Demo Deployment](ZERO_COST_DEPLOYMENT.md) for the public demo design.

## Next infrastructure unit

The next unit will add:

1. an Application Load Balancer.
2. an ECS cluster.
3. API and worker task definitions.
4. IAM roles with narrow permissions.
5. CloudWatch log groups.
6. service health checks and scaling rules.
