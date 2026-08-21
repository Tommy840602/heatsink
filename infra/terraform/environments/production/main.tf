module "thanos_storage" {
  source = "../../modules/aws-thanos-storage"

  bucket_name                       = var.bucket_name
  object_prefix                     = var.object_prefix
  cluster_oidc_provider_arn         = var.cluster_oidc_provider_arn
  cluster_oidc_issuer_url           = var.cluster_oidc_issuer_url
  name_prefix                       = var.name_prefix
  noncurrent_version_retention_days = var.noncurrent_version_retention_days

  tags = {
    DataClassification = "operational-metrics"
    RecoveryTier       = "production"
  }
}
