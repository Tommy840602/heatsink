output "bucket_name" {
  description = "S3 bucket consumed by the Thanos object-store renderer."
  value       = aws_s3_bucket.thanos.bucket
}

output "object_prefix" {
  description = "S3 prefix consumed by the Thanos object-store renderer."
  value       = var.object_prefix
}

output "kms_key_arn" {
  description = "KMS key ARN consumed by --sse-kms-key-id."
  value       = aws_kms_key.thanos.arn
}

output "receive_role_arn" {
  description = "IRSA role ARN consumed by the EKS manifest renderer."
  value       = aws_iam_role.thanos["receive"].arn
}

output "store_role_arn" {
  description = "IRSA role ARN consumed by the EKS manifest renderer."
  value       = aws_iam_role.thanos["store"].arn
}

output "compact_role_arn" {
  description = "IRSA role ARN consumed by the EKS manifest renderer."
  value       = aws_iam_role.thanos["compact"].arn
}
