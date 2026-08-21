variable "bucket_name" {
  description = "Globally unique S3 bucket name for Thanos blocks."
  type        = string

  validation {
    condition = (
      can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.bucket_name)) &&
      !can(regex("^[0-9]{1,3}(\\.[0-9]{1,3}){3}$", var.bucket_name)) &&
      !strcontains(var.bucket_name, "..") &&
      !strcontains(var.bucket_name, ".-") &&
      !strcontains(var.bucket_name, "-.") &&
      !startswith(var.bucket_name, "xn--") &&
      !startswith(var.bucket_name, "sthree-") &&
      !startswith(var.bucket_name, "amzn-s3-demo-") &&
      !endswith(var.bucket_name, "-s3alias") &&
      !endswith(var.bucket_name, "--ol-s3") &&
      !endswith(var.bucket_name, ".mrap") &&
      !endswith(var.bucket_name, "--x-s3") &&
      !endswith(var.bucket_name, "--table-s3")
    )
    error_message = "bucket_name must be a 3-63 character lowercase DNS-compatible S3 name."
  }
}

variable "object_prefix" {
  description = "Prefix containing all Thanos objects in the bucket."
  type        = string
  default     = "thermoform/metrics"

  validation {
    condition = (
      can(regex("^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}[A-Za-z0-9]$", var.object_prefix)) &&
      !strcontains(var.object_prefix, "//") &&
      alltrue([for segment in split("/", var.object_prefix) : !contains([".", ".."], segment)])
    )
    error_message = "object_prefix must be a safe relative S3 prefix without empty, dot, or parent segments."
  }
}

variable "cluster_oidc_provider_arn" {
  description = "ARN of the existing IAM OIDC provider for the target EKS cluster."
  type        = string

  validation {
    condition = can(regex(
      "^arn:(aws|aws-us-gov|aws-cn):iam::[0-9]{12}:oidc-provider/oidc\\.eks\\.[a-z0-9-]+\\.amazonaws\\.com(\\.cn)?/id/[A-Za-z0-9]+$",
      var.cluster_oidc_provider_arn,
    ))
    error_message = "cluster_oidc_provider_arn must identify one EKS IAM OIDC provider."
  }
}

variable "cluster_oidc_issuer_url" {
  description = "HTTPS issuer URL reported by the target EKS cluster."
  type        = string

  validation {
    condition = can(regex(
      "^https://oidc\\.eks\\.[a-z0-9-]+\\.amazonaws\\.com(\\.cn)?/id/[A-Za-z0-9]+$",
      var.cluster_oidc_issuer_url,
    ))
    error_message = "cluster_oidc_issuer_url must be a complete EKS OIDC issuer URL."
  }
}

variable "name_prefix" {
  description = "Prefix for IAM role and KMS alias names."
  type        = string
  default     = "thermoform-prod"

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9+=,.@_-]{1,31}$", var.name_prefix))
    error_message = "name_prefix must be 2-32 IAM-safe characters."
  }
}

variable "namespace" {
  description = "Kubernetes namespace containing the Thanos ServiceAccounts."
  type        = string
  default     = "thermoform-observability"

  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.namespace))
    error_message = "namespace must be a valid Kubernetes DNS label."
  }
}

variable "noncurrent_version_retention_days" {
  description = "Recovery window before S3 permanently removes noncurrent object versions."
  type        = number
  default     = 30

  validation {
    condition     = var.noncurrent_version_retention_days >= 30 && floor(var.noncurrent_version_retention_days) == var.noncurrent_version_retention_days
    error_message = "noncurrent_version_retention_days must be a whole number of at least 30 days."
  }
}

variable "abort_incomplete_multipart_days" {
  description = "Age after which incomplete multipart uploads are aborted."
  type        = number
  default     = 7

  validation {
    condition     = var.abort_incomplete_multipart_days >= 1 && var.abort_incomplete_multipart_days <= 30 && floor(var.abort_incomplete_multipart_days) == var.abort_incomplete_multipart_days
    error_message = "abort_incomplete_multipart_days must be a whole number from 1 through 30."
  }
}

variable "tags" {
  description = "Additional tags applied to managed AWS resources."
  type        = map(string)
  default     = {}
}
