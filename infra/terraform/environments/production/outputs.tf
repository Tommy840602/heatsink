output "bucket_name" {
  value = module.thanos_storage.bucket_name
}

output "object_prefix" {
  value = module.thanos_storage.object_prefix
}

output "kms_key_arn" {
  value = module.thanos_storage.kms_key_arn
}

output "receive_role_arn" {
  value = module.thanos_storage.receive_role_arn
}

output "store_role_arn" {
  value = module.thanos_storage.store_role_arn
}

output "compact_role_arn" {
  value = module.thanos_storage.compact_role_arn
}
