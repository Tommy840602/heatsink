variable "expected_aws_account_id" {
  description = "Only AWS account in which this root may plan resources."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_aws_account_id)) && var.expected_aws_account_id != "000000000000"
    error_message = "expected_aws_account_id must be a non-placeholder 12-digit account ID."
  }
}

variable "aws_region" {
  description = "AWS region containing the EKS cluster and Thanos resources."
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]$", var.aws_region))
    error_message = "aws_region must be an AWS region identifier."
  }
}

variable "bucket_name" {
  description = "Globally unique production Thanos bucket."
  type        = string
}

variable "object_prefix" {
  description = "Prefix containing production Thanos objects."
  type        = string
  default     = "thermoform/metrics"
}

variable "cluster_oidc_provider_arn" {
  description = "Existing IAM OIDC provider ARN for the production EKS cluster."
  type        = string

  validation {
    condition     = strcontains(var.cluster_oidc_provider_arn, ":${var.expected_aws_account_id}:oidc-provider/")
    error_message = "cluster_oidc_provider_arn must belong to expected_aws_account_id."
  }
}

variable "cluster_oidc_issuer_url" {
  description = "Issuer URL reported by the production EKS cluster."
  type        = string
}

variable "name_prefix" {
  description = "Production IAM and KMS resource prefix."
  type        = string
  default     = "thermoform-prod"

  validation {
    condition     = endswith(var.name_prefix, "-prod")
    error_message = "Production name_prefix must end in -prod."
  }
}

variable "noncurrent_version_retention_days" {
  description = "Recovery window for noncurrent Thanos object versions."
  type        = number
  default     = 30
}
