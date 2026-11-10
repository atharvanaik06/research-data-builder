# AWS Recruiter and Interview Guide

## Important statement

The repository contains a tested AWS infrastructure design. I did not apply it because I set a zero-cost rule for this portfolio project.

The live demo uses free services. The AWS design shows how I would run the same system in production.

Do not say that you deployed the AWS resources. Say that you designed, coded, and validated the AWS infrastructure.

## 30-second explanation

I designed the production AWS architecture with Terraform. It uses ECS Fargate for the API and worker, RDS PostgreSQL for durable state, SQS for jobs, and S3 for exports. I placed compute and the database in private subnets. I added encryption, managed secrets, backups, and a dead-letter queue. CI validates the Terraform files on every change. I did not apply the infrastructure because NAT Gateway, RDS, and Fargate can create recurring costs. I deployed a zero-cost demo topology instead.

## Two-minute explanation

The application has two work types. The API handles short browser requests. The worker handles long dataset builds.

In the AWS design, an Application Load Balancer sends traffic to API tasks on ECS Fargate. SQS separates API requests from worker execution. Worker tasks read jobs and write build state to RDS PostgreSQL. They store export files in a private S3 bucket.

The VPC uses two availability zones. Public subnets hold the load balancer. Private subnets hold ECS tasks. Isolated database subnets hold RDS.

Security groups allow only required network paths. The database accepts traffic only from the application tasks. S3 blocks public access.

KMS encrypts stored data. Secrets Manager holds managed credentials. RDS uses backups. SQS sends repeated failures to a dead-letter queue.

The development design uses one NAT Gateway to reduce cost. The production design uses one NAT Gateway in each availability zone. Production also enables Multi-AZ RDS and deletion protection.

I used Terraform so reviewers can inspect and repeat the design. GitHub Actions enforces formatting and validates both Terraform units without creating resources.

## What each AWS service does

| AWS service | Purpose in this system | Design reason |
|---|---|---|
| VPC | Controls network boundaries | Keeps compute and data services private |
| Application Load Balancer | Receives HTTPS requests | Gives the API one public entry point |
| ECS Fargate | Runs API and worker containers | Removes server maintenance |
| ECR | Stores container images | Gives ECS a private image source |
| RDS PostgreSQL | Stores users, recipes, jobs, and lineage | Provides transactions and managed backups |
| SQS | Holds build jobs | Separates fast API work from long builds |
| SQS dead-letter queue | Holds repeated failures | Supports inspection and safe replay |
| S3 | Stores export bundles | Fits durable file storage better than PostgreSQL |
| KMS | Encrypts stored data | Centralizes key control |
| Secrets Manager | Stores credentials | Keeps secrets out of code and Terraform inputs |
| CloudWatch | Stores logs and metrics | Supports alarms and incident review |

## Key trade-offs

### NAT Gateway cost and reliability

A NAT Gateway gives private tasks internet access to FRED and World Bank. It also creates an hourly and data-processing charge.

Development uses one NAT Gateway. This choice lowers cost but creates one availability-zone dependency.

Production uses one NAT Gateway in each availability zone. This choice costs more but removes that dependency.

### RDS cost and reliability

Development uses a small single-AZ database. Production uses Multi-AZ RDS and deletion protection.

Multi-AZ costs more. It gives the production database a standby instance for failures.

### SQS instead of an in-process queue

SQS keeps jobs after a worker restart. It also lets the API and worker scale separately.

The zero-cost demo uses PostgreSQL as its durable queue. It runs the worker inside the API service because free Render workers are not available.

### S3 instead of PostgreSQL for files

PostgreSQL stores searchable workflow data. S3 stores large export files.

This split keeps database backups smaller. It also gives the application a storage service that can scale independently.

## Questions that an interviewer can ask

### Why did you use private subnets?

The API tasks and database do not need direct public addresses. Private subnets reduce the exposed surface.

### How does a failed job move through the system?

The worker records progress and retries temporary failures. SQS moves a job to the dead-letter queue after repeated delivery failures.

### How do you protect research exports?

S3 blocks public access and uses encryption. The API requires matching user ownership before it loads a file. The application compares the checksum before download.

### How do you prevent duplicate work?

The database uses deterministic build identities and atomic job claims. Worker leases prevent concurrent execution of one attempt.

### Why did you not use AWS for the public demo?

The project has a zero-cost rule. NAT Gateway, RDS, and Fargate can create recurring charges. I kept the AWS design as validated infrastructure code.

### What would you do before a production launch?

I would finish ECS services, IAM roles, alarms, deployment automation, and recovery tests. I would also review the Terraform plan and cost estimate.

## Honest resume wording

Use this statement:

> Designed and validated a Terraform AWS architecture for a multi-user research-data platform. The design uses ECS Fargate, RDS PostgreSQL, SQS, S3, KMS, Secrets Manager, and private VPC networking. Added environment-specific reliability and cost controls. Deployed a separate zero-cost demo topology to avoid recurring cloud charges.

Do not use the word “deployed” for the AWS architecture until you apply it and test the live resources.
