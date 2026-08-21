#!/usr/bin/env python3
"""Validate the fail-closed AWS bootstrap CloudFormation contract."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


class ContractError(ValueError):
    """Raised when the bootstrap template weakens a required invariant."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _block(text: str, start: str, end: str) -> str:
    _require(start in text, f"missing block: {start}")
    _require(end in text.split(start, 1)[1], f"missing block boundary: {end}")
    return text.split(start, 1)[1].split(end, 1)[0]


def validate(template_path: Path) -> None:
    text = template_path.read_text(encoding="utf-8")
    key = _block(text, "  StateKeyEncryptionKey:\n", "  StateKeyAlias:\n")
    bucket = _block(text, "  StateBucket:\n", "  StateBucketPolicy:\n")
    bucket_policy = _block(text, "  StateBucketPolicy:\n", "  GitHubOidcProvider:\n")
    provider = _block(text, "  GitHubOidcProvider:\n", "  TerraformPlanRole:\n")
    role = _block(text, "  TerraformPlanRole:\n", "Outputs:\n")
    trust = _block(role, "      AssumeRolePolicyDocument:\n", "      Policies:\n")
    state_access = _block(role, "              - Sid: ReadAndWriteStateObject\n", "              - Sid: OperateExactLockObject\n")
    lock_access = _block(role, "              - Sid: OperateExactLockObject\n", "              - Sid: UseStateEncryptionKeyThroughS3\n")

    for name, block in (("state key", key), ("state bucket", bucket), ("bucket policy", bucket_policy), ("OIDC provider", provider)):
        _require("    DeletionPolicy: Retain" in block, f"{name} must be retained on stack deletion")
        _require("    UpdateReplacePolicy: Retain" in block, f"{name} must be retained on replacement")

    for requirement in (
        "EnableKeyRotation: true",
        "PendingWindowInDays: 30",
        "SSEAlgorithm: aws:kms",
        "ObjectOwnership: BucketOwnerEnforced",
        "BlockPublicAcls: true",
        "BlockPublicPolicy: true",
        "IgnorePublicAcls: true",
        "RestrictPublicBuckets: true",
        "Status: Enabled",
    ):
        _require(requirement in text, f"missing state safety control: {requirement}")
    _require("aws:SecureTransport: \"false\"" in bucket_policy, "bucket policy must deny plaintext transport")
    _require("NoncurrentVersionExpiration" not in bucket, "state recovery versions must not expire automatically")

    _require("Default: \"false\"" in _block(text, "  CreateGitHubOidcProvider:\n", "  PlanRoleName:\n"), "OIDC creation must be opt-in")
    _require("Url: https://token.actions.githubusercontent.com" in provider, "unexpected GitHub OIDC issuer")
    _require("- sts.amazonaws.com" in provider, "GitHub OIDC audience is missing")
    _require(
        "^repo:[A-Za-z0-9_.-]+(@[0-9]+)?/[A-Za-z0-9_.-]+(@[0-9]+)?:environment:production-plan$"
        in text,
        "exact legacy/immutable Environment subject constraint is missing",
    )
    _require("StringEquals:" in trust, "OIDC audience and subject must use exact equality")
    _require("StringLike:" not in trust, "OIDC trust must not use wildcard matching")
    _require("token.actions.githubusercontent.com:aud: sts.amazonaws.com" in trust, "OIDC audience is not exact")
    _require("token.actions.githubusercontent.com:sub: !Ref GitHubOidcSubject" in trust, "OIDC subject is not exact")
    _require("sts:AssumeRoleWithWebIdentity" in trust, "web identity action is missing")

    _require("s3:PutObject" in state_access, "Terraform backend must be able to write state")
    _require("s3:DeleteObject" not in state_access, "plan role must not delete the state object")
    _require("${StateBucket.Arn}/${StateKey}" in state_access, "state access must target one exact object")
    for action in ("s3:GetObject", "s3:PutObject", "s3:DeleteObject"):
        _require(action in lock_access, f"lock object is missing {action}")
    _require("${StateBucket.Arn}/${StateKey}.tflock" in lock_access, "lock access must target one exact object")
    _require(role.count("s3:DeleteObject") == 1, "only the exact lock object may be deleted")
    _require("kms:ViaService: !Sub s3.${AWS::Region}.${AWS::URLSuffix}" in role, "state KMS use must be bound to S3")

    for forbidden in (
        "iam:Create",
        "iam:Delete",
        "iam:Put",
        "iam:Update",
        "kms:Create",
        "kms:Disable",
        "kms:ScheduleKeyDeletion",
        "s3:CreateBucket",
        "s3:DeleteBucket",
        "s3:PutBucket",
    ):
        _require(forbidden not in role, f"plan role contains mutating infrastructure action: {forbidden}")
    for requirement in (
        "Sid: ReadPlannedThanosBucketConfiguration",
        "Sid: ReadPlannedThanosRoles",
        "Sid: ReadTaggedProductionKmsKeys",
        "aws:ResourceTag/Application: thermoform",
        "aws:ResourceTag/Environment: production",
    ):
        _require(requirement in role, f"missing bounded refresh permission: {requirement}")

    _require("StateAndDataBucketsAreDistinct:" in text, "state/data bucket separation rule is missing")
    for output in ("StateBucketName", "StateKey", "StateKmsKeyArn", "TerraformPlanRoleArn", "GitHubOidcProviderArn"):
        _require(re.search(rf"(?m)^  {output}:$", text) is not None, f"missing bootstrap output: {output}")
    for forbidden in ("aws_access_key_id", "aws_secret_access_key", "access_key:", "secret_key:"):
        _require(forbidden not in text.lower(), f"static credential field found: {forbidden}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template", type=Path)
    args = parser.parse_args()
    try:
        validate(args.template)
    except (OSError, ContractError) as exc:
        parser.error(str(exc))
    print("AWS production bootstrap contract is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
