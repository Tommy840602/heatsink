locals {
  oidc_issuer = trimprefix(var.cluster_oidc_issuer_url, "https://")
  object_arn  = "${aws_s3_bucket.thanos.arn}/${var.object_prefix}/*"
  common_tags = merge(var.tags, {
    Application = "thermoform"
    Component   = "thanos"
    ManagedBy   = "terraform"
  })
  service_accounts = {
    receive = "thanos-receive"
    store   = "thanos-store"
    compact = "thanos-compact"
  }
  object_actions = {
    receive = [
      "s3:AbortMultipartUpload",
      "s3:GetObject",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]
    store = [
      "s3:GetObject",
    ]
    compact = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]
  }
  bucket_actions = {
    receive = ["s3:ListBucket", "s3:ListBucketMultipartUploads"]
    store   = ["s3:ListBucket"]
    compact = ["s3:ListBucket", "s3:ListBucketMultipartUploads"]
  }
  kms_actions = {
    receive = ["kms:Decrypt", "kms:DescribeKey", "kms:Encrypt", "kms:GenerateDataKey"]
    store   = ["kms:Decrypt", "kms:DescribeKey"]
    compact = ["kms:Decrypt", "kms:DescribeKey", "kms:Encrypt", "kms:GenerateDataKey"]
  }
}

check "oidc_provider_matches_issuer" {
  assert {
    condition     = endswith(var.cluster_oidc_provider_arn, "oidc-provider/${local.oidc_issuer}")
    error_message = "OIDC provider ARN and cluster issuer URL must identify the same provider."
  }
}

resource "aws_kms_key" "thanos" {
  description             = "Thanos object-store encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  key_usage               = "ENCRYPT_DECRYPT"

  lifecycle {
    prevent_destroy = true
  }

  tags = local.common_tags
}

resource "aws_kms_alias" "thanos" {
  name          = "alias/${var.name_prefix}-thanos"
  target_key_id = aws_kms_key.thanos.key_id
}

resource "aws_s3_bucket" "thanos" {
  bucket        = var.bucket_name
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }

  tags = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "thanos" {
  bucket = aws_s3_bucket.thanos.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "thanos" {
  bucket = aws_s3_bucket.thanos.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "thanos" {
  bucket = aws_s3_bucket.thanos.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "thanos" {
  bucket = aws_s3_bucket.thanos.id

  rule {
    bucket_key_enabled = true

    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.thanos.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "thanos" {
  bucket = aws_s3_bucket.thanos.id

  depends_on = [aws_s3_bucket_versioning.thanos]

  rule {
    id     = "recoverable-version-and-multipart-cleanup"
    status = "Enabled"

    filter {
      prefix = var.object_prefix
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = var.abort_incomplete_multipart_days
    }

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_retention_days
    }
  }
}

data "aws_iam_policy_document" "bucket_transport" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    actions = [
      "s3:*",
    ]
    resources = [
      aws_s3_bucket.thanos.arn,
      "${aws_s3_bucket.thanos.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "thanos" {
  bucket = aws_s3_bucket.thanos.id
  policy = data.aws_iam_policy_document.bucket_transport.json

  depends_on = [aws_s3_bucket_public_access_block.thanos]
}

data "aws_iam_policy_document" "irsa_trust" {
  for_each = local.service_accounts

  statement {
    sid     = "ExactServiceAccountWebIdentity"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.cluster_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_issuer}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_issuer}:sub"
      values   = ["system:serviceaccount:${var.namespace}:${each.value}"]
    }
  }
}

resource "aws_iam_role" "thanos" {
  for_each = local.service_accounts

  name                 = "${var.name_prefix}-thanos-${each.key}"
  assume_role_policy   = data.aws_iam_policy_document.irsa_trust[each.key].json
  max_session_duration = 3600

  tags = local.common_tags
}

data "aws_iam_policy_document" "workload" {
  for_each = local.service_accounts

  statement {
    sid       = "ListThanosPrefix"
    effect    = "Allow"
    actions   = local.bucket_actions[each.key]
    resources = [aws_s3_bucket.thanos.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = [var.object_prefix, "${var.object_prefix}/*"]
    }
  }

  statement {
    sid       = "AccessThanosObjects"
    effect    = "Allow"
    actions   = local.object_actions[each.key]
    resources = [local.object_arn]
  }

  statement {
    sid       = "UseThanosKmsKey"
    effect    = "Allow"
    actions   = local.kms_actions[each.key]
    resources = [aws_kms_key.thanos.arn]
  }
}

resource "aws_iam_role_policy" "thanos" {
  for_each = local.service_accounts

  name   = "${var.name_prefix}-thanos-${each.key}"
  role   = aws_iam_role.thanos[each.key].id
  policy = data.aws_iam_policy_document.workload[each.key].json
}
