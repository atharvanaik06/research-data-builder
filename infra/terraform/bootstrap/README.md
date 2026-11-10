# Terraform State Bootstrap

This configuration creates the private S3 bucket that stores Terraform state. Apply it once before you apply the platform configuration.

```bash
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan
terraform apply
```

Replace the example bucket name before the plan. The bucket keeps version history and blocks all public access.

Do not store provider keys, passwords, or AWS access keys in a Terraform variable file.
