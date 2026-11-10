locals {
  name_prefix = "${var.project_name}-${var.environment}"
  azs         = slice(data.aws_availability_zones.available.names, 0, 2)
  az_map      = { for index, az in local.azs : az => index }
  nat_az_map  = var.single_nat_gateway ? { (local.azs[0]) = 0 } : local.az_map

  common_tags = merge(
    {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    },
    var.tags,
  )
}
