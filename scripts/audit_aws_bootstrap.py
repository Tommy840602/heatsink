#!/usr/bin/env python3
"""Read-only preflight and drift audit for the production AWS bootstrap."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any


ACCOUNT_PATTERN = re.compile(r"^[0-9]{12}$")
REGION_PATTERN = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-[0-9]$")
NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,127}$")
BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
STATE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{1,254}\.tfstate$")
ROLE_PATTERN = re.compile(r"^[A-Za-z0-9+=,.@_-]{1,64}$")
PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+=,.@_-]{1,31}$")
SUBJECT_PATTERN = re.compile(
    r"^repo:[A-Za-z0-9_.-]+(?:@[0-9]+)?/"
    r"[A-Za-z0-9_.-]+(?:@[0-9]+)?:environment:production-plan$"
)

BASE_RESOURCES = {
    "StateKeyEncryptionKey": "AWS::KMS::Key",
    "StateKeyAlias": "AWS::KMS::Alias",
    "StateBucket": "AWS::S3::Bucket",
    "StateBucketPolicy": "AWS::S3::BucketPolicy",
    "TerraformPlanRole": "AWS::IAM::Role",
}
OIDC_RESOURCE = {"GitHubOidcProvider": "AWS::IAM::OIDCProvider"}
PLAN_POLICY_NAME = "production-terraform-plan"


class AuditError(ValueError):
    """Raised when a remote bootstrap target violates the reviewed contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def _safe_bucket(value: str, label: str) -> str:
    _require(BUCKET_PATTERN.fullmatch(value) is not None, f"invalid {label}")
    _require(not any(part in value for part in ("..", ".-", "-.")), f"unsafe {label}")
    _require(
        not value.startswith(("xn--", "sthree-", "amzn-s3-demo-"))
        and not value.endswith(("-s3alias", "--ol-s3", ".mrap", "--x-s3", "--table-s3")),
        f"reserved {label}",
    )
    return value


def validate_inputs(values: argparse.Namespace) -> None:
    _require(ACCOUNT_PATTERN.fullmatch(values.account_id) is not None, "invalid AWS account ID")
    _require(values.account_id != "000000000000", "placeholder AWS account ID is forbidden")
    _require(REGION_PATTERN.fullmatch(values.region) is not None, "invalid AWS region")
    _require(NAME_PATTERN.fullmatch(values.stack_name) is not None, "invalid stack name")
    _safe_bucket(values.state_bucket, "state bucket")
    _safe_bucket(values.thanos_bucket, "Thanos bucket")
    _require(values.state_bucket != values.thanos_bucket, "state and Thanos buckets must differ")
    _require(STATE_KEY_PATTERN.fullmatch(values.state_key) is not None, "invalid state key")
    _require("//" not in values.state_key, "state key contains an empty segment")
    _require(all(part not in {".", ".."} for part in values.state_key.split("/")), "unsafe state key")
    _require(SUBJECT_PATTERN.fullmatch(values.github_subject) is not None, "invalid exact GitHub OIDC subject")
    _require(ROLE_PATTERN.fullmatch(values.plan_role_name) is not None, "invalid plan role name")
    _require(PREFIX_PATTERN.fullmatch(values.name_prefix) is not None, "invalid Terraform name prefix")
    if hasattr(values, "change_set_name"):
        _require(NAME_PATTERN.fullmatch(values.change_set_name) is not None, "invalid change-set name")
        _require(values.template.is_file(), "reviewed bootstrap template does not exist")


class AwsContext:
    def __init__(self, *, region: str, profile: str | None = None) -> None:
        self.region = region
        self.profile = profile


def _aws_json(
    service: str,
    operation: str,
    *arguments: str,
    context: AwsContext,
    absent_error: str | None = None,
) -> dict[str, Any]:
    command = ["aws", service, operation, *arguments, "--region", context.region]
    if context.profile:
        command.extend(["--profile", context.profile])
    command.extend(["--output", "json", "--no-cli-pager", "--no-cli-auto-prompt"])
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload = json.loads(result.stdout)
    except FileNotFoundError as exc:
        raise AuditError("AWS CLI v2 is required") from exc
    except subprocess.TimeoutExpired as exc:
        raise AuditError(f"AWS read timed out: {service} {operation}") from exc
    except subprocess.CalledProcessError as exc:
        if absent_error and absent_error in (exc.stderr or ""):
            return {}
        detail = (exc.stderr or "AWS CLI read failed").strip().splitlines()[-1][:400]
        raise AuditError(f"AWS read failed for {service} {operation}: {detail}") from exc
    except json.JSONDecodeError as exc:
        raise AuditError(f"AWS returned invalid JSON for {service} {operation}") from exc
    _require(isinstance(payload, dict), f"AWS returned a non-object for {service} {operation}")
    return payload


def validate_caller(payload: dict[str, Any], expected_account: str) -> str:
    account = str(payload.get("Account", ""))
    arn = str(payload.get("Arn", ""))
    _require(account == expected_account, "AWS caller account does not match --account-id")
    match = re.fullmatch(r"arn:(aws|aws-us-gov|aws-cn):[^:]+::[0-9]{12}:.+", arn)
    _require(match is not None, "AWS caller ARN is malformed")
    return match.group(1)


def _normalize_template(value: str) -> str:
    return value.replace("\r\n", "\n").rstrip() + "\n"


def template_digest(value: str) -> str:
    return hashlib.sha256(_normalize_template(value).encode("utf-8")).hexdigest()


def expected_parameters(values: argparse.Namespace) -> dict[str, str]:
    return {
        "StateBucketName": values.state_bucket,
        "StateKey": values.state_key,
        "ThanosBucketName": values.thanos_bucket,
        "GitHubOidcSubject": values.github_subject,
        "CreateGitHubOidcProvider": values.create_oidc_provider,
        "PlanRoleName": values.plan_role_name,
        "TerraformNamePrefix": values.name_prefix,
    }


def _parameter_map(items: Any) -> dict[str, str]:
    _require(isinstance(items, list), "CloudFormation parameters are malformed")
    result: dict[str, str] = {}
    for item in items:
        _require(isinstance(item, dict), "CloudFormation parameter is malformed")
        key = item.get("ParameterKey")
        value = item.get("ParameterValue")
        _require(isinstance(key, str) and isinstance(value, str), "CloudFormation parameter is unresolved")
        result[key] = value
    return result


def validate_change_set(
    payload: dict[str, Any],
    *,
    stack_name: str,
    change_set_name: str,
    parameters: dict[str, str],
    create_oidc_provider: bool,
) -> list[dict[str, str]]:
    _require(payload.get("StackName") == stack_name, "change set belongs to the wrong stack")
    name_or_id = str(payload.get("ChangeSetName", ""))
    _require(
        name_or_id == change_set_name or f"changeSet/{change_set_name}/" in name_or_id,
        "unexpected change-set identity",
    )
    _require(payload.get("ChangeSetType") == "CREATE", "bootstrap change set must be CREATE")
    _require(payload.get("Status") == "CREATE_COMPLETE", "change set is not fully created")
    _require(payload.get("ExecutionStatus") == "AVAILABLE", "change set is not available for review")
    _require(set(payload.get("Capabilities", [])) == {"CAPABILITY_NAMED_IAM"}, "unexpected CloudFormation capabilities")
    _require(_parameter_map(payload.get("Parameters")) == parameters, "change-set parameters do not exactly match review inputs")
    _require("NextToken" not in payload, "change-set response is truncated")

    expected = dict(BASE_RESOURCES)
    if create_oidc_provider:
        expected.update(OIDC_RESOURCE)
    actual: dict[str, str] = {}
    summary: list[dict[str, str]] = []
    changes = payload.get("Changes")
    _require(isinstance(changes, list), "change-set resources are malformed")
    for item in changes:
        resource = item.get("ResourceChange", {}) if isinstance(item, dict) else {}
        logical_id = resource.get("LogicalResourceId")
        resource_type = resource.get("ResourceType")
        action = resource.get("Action")
        replacement = resource.get("Replacement")
        _require(isinstance(logical_id, str) and isinstance(resource_type, str), "resource change is malformed")
        _require(action == "Add", f"bootstrap change must only add resources: {logical_id}")
        _require(replacement in {None, "False"}, f"replacement is forbidden: {logical_id}")
        _require(logical_id not in actual, f"duplicate resource change: {logical_id}")
        actual[logical_id] = resource_type
        summary.append({"action": "Add", "logical_id": logical_id, "type": resource_type})
    _require(actual == expected, "change-set resource inventory does not match the reviewed bootstrap")
    return sorted(summary, key=lambda item: item["logical_id"])


def validate_template(payload: dict[str, Any], reviewed_template: str) -> str:
    remote = payload.get("TemplateBody")
    _require(isinstance(remote, str), "CloudFormation did not return the original template text")
    reviewed_digest = template_digest(reviewed_template)
    _require(template_digest(remote) == reviewed_digest, "change-set template differs from the reviewed local template")
    return reviewed_digest


def change_set_audit(values: argparse.Namespace) -> dict[str, Any]:
    validate_inputs(values)
    context = AwsContext(region=values.region, profile=values.profile)
    partition = validate_caller(
        _aws_json("sts", "get-caller-identity", context=context), values.account_id
    )
    change_set = _aws_json(
        "cloudformation",
        "describe-change-set",
        "--stack-name",
        values.stack_name,
        "--change-set-name",
        values.change_set_name,
        "--include-property-values",
        context=context,
    )
    resources = validate_change_set(
        change_set,
        stack_name=values.stack_name,
        change_set_name=values.change_set_name,
        parameters=expected_parameters(values),
        create_oidc_provider=values.create_oidc_provider == "true",
    )
    template = _aws_json(
        "cloudformation",
        "get-template",
        "--stack-name",
        values.stack_name,
        "--change-set-name",
        values.change_set_name,
        "--template-stage",
        "Original",
        context=context,
    )
    digest = validate_template(template, values.template.read_text(encoding="utf-8"))
    return {
        "account": values.account_id,
        "change_set": values.change_set_name,
        "mode": "change-set",
        "partition": partition,
        "region": values.region,
        "resources": resources,
        "stack": values.stack_name,
        "status": "ready-for-human-review",
        "template_sha256": digest,
    }


def _output_map(items: Any) -> dict[str, str]:
    _require(isinstance(items, list), "stack outputs are malformed")
    result: dict[str, str] = {}
    for item in items:
        _require(isinstance(item, dict), "stack output is malformed")
        key = item.get("OutputKey")
        value = item.get("OutputValue")
        _require(isinstance(key, str) and isinstance(value, str), "stack output is unresolved")
        result[key] = value
    return result


def validate_stack(
    payload: dict[str, Any],
    *,
    values: argparse.Namespace,
    partition: str,
) -> tuple[dict[str, str], dict[str, str]]:
    stacks = payload.get("Stacks")
    _require(isinstance(stacks, list) and len(stacks) == 1, "expected exactly one bootstrap stack")
    stack = stacks[0]
    _require(stack.get("StackName") == values.stack_name, "unexpected deployed stack")
    _require(stack.get("StackStatus") in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}, "bootstrap stack is not stable")
    _require(stack.get("EnableTerminationProtection") is True, "bootstrap stack termination protection is required")
    _require(set(stack.get("Capabilities", [])) == {"CAPABILITY_NAMED_IAM"}, "unexpected deployed stack capabilities")
    _require(_parameter_map(stack.get("Parameters")) == expected_parameters(values), "deployed stack parameters drifted")

    role_arn = f"arn:{partition}:iam::{values.account_id}:role/{values.plan_role_name}"
    provider_arn = (
        f"arn:{partition}:iam::{values.account_id}:"
        "oidc-provider/token.actions.githubusercontent.com"
    )
    outputs = _output_map(stack.get("Outputs"))
    expected_outputs = {
        "StateBucketName": values.state_bucket,
        "StateKey": values.state_key,
        "TerraformPlanRoleArn": role_arn,
        "GitHubOidcProviderArn": provider_arn,
    }
    for key, expected in expected_outputs.items():
        _require(outputs.get(key) == expected, f"unexpected stack output: {key}")
    kms_arn = outputs.get("StateKmsKeyArn", "")
    _require(
        re.fullmatch(
            rf"arn:{re.escape(partition)}:kms:{re.escape(values.region)}:"
            rf"{values.account_id}:key/[A-Za-z0-9-]+",
            kms_arn,
        )
        is not None,
        "invalid state KMS output",
    )
    return outputs, {"provider_arn": provider_arn, "role_arn": role_arn}


def validate_stack_resources(
    payload: dict[str, Any], *, create_oidc_provider: bool
) -> dict[str, str]:
    items = payload.get("StackResources")
    _require(isinstance(items, list), "stack resources are malformed")
    expected = dict(BASE_RESOURCES)
    if create_oidc_provider:
        expected.update(OIDC_RESOURCE)
    actual: dict[str, str] = {}
    for item in items:
        _require(isinstance(item, dict), "stack resource is malformed")
        logical_id = item.get("LogicalResourceId")
        resource_type = item.get("ResourceType")
        status = str(item.get("ResourceStatus", ""))
        _require(isinstance(logical_id, str) and isinstance(resource_type, str), "stack resource identity is malformed")
        _require(status.endswith("_COMPLETE"), f"stack resource is not complete: {logical_id}")
        actual[logical_id] = resource_type
    _require(actual == expected, "deployed resource inventory differs from bootstrap contract")
    return actual


def validate_bucket(
    *,
    name: str,
    partition: str,
    region: str,
    kms_arn: str,
    location: dict[str, Any],
    versioning: dict[str, Any],
    public_access: dict[str, Any],
    encryption: dict[str, Any],
    ownership: dict[str, Any],
    policy_status: dict[str, Any],
    policy: dict[str, Any],
    tags: dict[str, Any],
    lifecycle: dict[str, Any],
) -> None:
    location_value = location.get("LocationConstraint")
    actual_region = "us-east-1" if location_value is None else str(location_value)
    if actual_region == "EU":
        actual_region = "eu-west-1"
    _require(actual_region == region, "state bucket is in the wrong region")
    _require(versioning.get("Status") == "Enabled", "state bucket versioning is not enabled")
    block = public_access.get("PublicAccessBlockConfiguration", {})
    for key in ("BlockPublicAcls", "BlockPublicPolicy", "IgnorePublicAcls", "RestrictPublicBuckets"):
        _require(block.get(key) is True, f"state bucket public access control drifted: {key}")
    rules = encryption.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
    _require(isinstance(rules, list) and len(rules) == 1, "state bucket encryption rules drifted")
    default = rules[0].get("ApplyServerSideEncryptionByDefault", {})
    _require(default.get("SSEAlgorithm") == "aws:kms", "state bucket is not using KMS encryption")
    _require(default.get("KMSMasterKeyID") == kms_arn, "state bucket uses the wrong KMS key")
    _require(rules[0].get("BucketKeyEnabled") is False, "state bucket key mode drifted")
    ownership_rules = ownership.get("OwnershipControls", {}).get("Rules", [])
    _require(
        ownership_rules == [{"ObjectOwnership": "BucketOwnerEnforced"}],
        "state bucket ownership controls drifted",
    )
    _require(policy_status.get("PolicyStatus", {}).get("IsPublic") is False, "state bucket policy is public")

    document = policy.get("Policy")
    if isinstance(document, str):
        try:
            document = json.loads(document)
        except json.JSONDecodeError as exc:
            raise AuditError("state bucket policy is invalid JSON") from exc
    _require(isinstance(document, dict), "state bucket policy is malformed")
    statements = document.get("Statement")
    if isinstance(statements, dict):
        statements = [statements]
    _require(isinstance(statements, list) and len(statements) == 1, "state bucket policy has unexpected statements")
    statement = statements[0]
    resources = _as_set(statement.get("Resource"))
    _require(statement.get("Sid") == "DenyInsecureTransport", "TLS deny statement is missing")
    _require(statement.get("Effect") == "Deny", "TLS statement must deny")
    _require(statement.get("Principal") == "*", "TLS deny principal drifted")
    _require(_as_set(statement.get("Action")) == {"s3:*"}, "TLS deny action drifted")
    _require(
        resources
        == {f"arn:{partition}:s3:::{name}", f"arn:{partition}:s3:::{name}/*"},
        "TLS deny resources drifted",
    )
    _require(statement.get("Condition", {}).get("Bool", {}).get("aws:SecureTransport") == "false", "TLS deny condition drifted")

    tag_map = {item.get("Key"): item.get("Value") for item in tags.get("TagSet", [])}
    for key, value in {
        "Application": "thermoform",
        "Environment": "production",
        "DataClassification": "terraform-state",
        "ManagedBy": "cloudformation-bootstrap",
    }.items():
        _require(tag_map.get(key) == value, f"state bucket tag drifted: {key}")
    for rule in lifecycle.get("Rules", []):
        _require(
            "Expiration" not in rule and "NoncurrentVersionExpiration" not in rule,
            "state bucket lifecycle may not expire current or noncurrent state",
        )


def validate_kms(
    description: dict[str, Any], rotation: dict[str, Any], tags: dict[str, Any], kms_arn: str
) -> None:
    metadata = description.get("KeyMetadata", {})
    _require(metadata.get("Arn") == kms_arn, "state KMS key ARN drifted")
    _require(metadata.get("Enabled") is True and metadata.get("KeyState") == "Enabled", "state KMS key is not enabled")
    _require(metadata.get("KeyUsage") == "ENCRYPT_DECRYPT", "state KMS key usage drifted")
    _require(metadata.get("KeySpec") == "SYMMETRIC_DEFAULT", "state KMS key spec drifted")
    _require(metadata.get("MultiRegion") in {False, None}, "state KMS key must not be multi-region")
    _require(rotation.get("KeyRotationEnabled") is True, "state KMS rotation is not enabled")
    tag_map = {item.get("TagKey"): item.get("TagValue") for item in tags.get("Tags", [])}
    for key, value in {
        "Application": "thermoform",
        "Environment": "production",
        "ManagedBy": "cloudformation-bootstrap",
    }.items():
        _require(tag_map.get(key) == value, f"state KMS tag drifted: {key}")


def validate_kms_aliases(payload: dict[str, Any], kms_arn: str) -> None:
    aliases = payload.get("Aliases")
    _require(isinstance(aliases, list), "state KMS aliases are malformed")
    matching = [
        item
        for item in aliases
        if isinstance(item, dict)
        and item.get("AliasName") == "alias/thermoform-production-terraform-state"
    ]
    _require(len(matching) == 1, "state KMS alias is missing or duplicated")
    target = str(matching[0].get("TargetKeyId", ""))
    _require(kms_arn.endswith(f"key/{target}"), "state KMS alias targets the wrong key")


def _as_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    _require(isinstance(value, list) and all(isinstance(item, str) for item in value), "IAM value is malformed")
    return set(value)


def _statement_map(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    statements = document.get("Statement")
    if isinstance(statements, dict):
        statements = [statements]
    _require(isinstance(statements, list), "IAM statements are malformed")
    result: dict[str, dict[str, Any]] = {}
    for statement in statements:
        _require(isinstance(statement, dict) and isinstance(statement.get("Sid"), str), "IAM statement is malformed")
        sid = statement["Sid"]
        _require(sid not in result, f"duplicate IAM statement: {sid}")
        result[sid] = statement
    return result


def validate_oidc(
    payload: dict[str, Any], github_subject: str, *, require_managed_tags: bool
) -> None:
    _require(payload.get("Url") == "token.actions.githubusercontent.com", "unexpected GitHub OIDC URL")
    _require(set(payload.get("ClientIDList", [])) == {"sts.amazonaws.com"}, "unexpected GitHub OIDC audience")
    thumbprints = payload.get("ThumbprintList", [])
    _require(
        isinstance(thumbprints, list)
        and 1 <= len(thumbprints) <= 5
        and all(re.fullmatch(r"[0-9a-fA-F]{40}", str(item)) for item in thumbprints),
        "GitHub OIDC thumbprints are malformed",
    )
    if require_managed_tags:
        tag_map = {item.get("Key"): item.get("Value") for item in payload.get("Tags", [])}
        _require(tag_map.get("Application") == "thermoform", "GitHub OIDC Application tag drifted")
        _require(tag_map.get("ManagedBy") == "cloudformation-bootstrap", "GitHub OIDC ManagedBy tag drifted")
    _require(SUBJECT_PATTERN.fullmatch(github_subject) is not None, "GitHub subject is malformed")


def _expected_policy(
    *,
    account: str,
    region: str,
    partition: str,
    state_bucket: str,
    state_key: str,
    thanos_bucket: str,
    kms_arn: str,
    name_prefix: str,
) -> dict[str, tuple[set[str], set[str], dict[str, Any] | None]]:
    state_arn = f"arn:{partition}:s3:::{state_bucket}/{state_key}"
    lock_arn = f"{state_arn}.tflock"
    roles = {
        f"arn:{partition}:iam::{account}:role/{name_prefix}-thanos-{component}"
        for component in ("receive", "store", "compact")
    }
    return {
        "ListExactStateObjects": (
            {"s3:ListBucket"},
            {f"arn:{partition}:s3:::{state_bucket}"},
            {"StringEquals": {"s3:prefix": [state_key, f"{state_key}.tflock"]}},
        ),
        "ReadAndWriteStateObject": (
            {"s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"},
            {state_arn},
            None,
        ),
        "OperateExactLockObject": (
            {"s3:GetObject", "s3:PutObject", "s3:DeleteObject"},
            {lock_arn},
            None,
        ),
        "UseStateEncryptionKeyThroughS3": (
            {"kms:Decrypt", "kms:DescribeKey", "kms:Encrypt", "kms:GenerateDataKey"},
            {kms_arn},
            {
                "StringEquals": {
                    "kms:CallerAccount": account,
                    "kms:ViaService": f"s3.{region}.{_dns_suffix(partition)}",
                }
            },
        ),
        "ConfirmCallerAccount": ({"sts:GetCallerIdentity"}, {"*"}, None),
        "ReadPlannedThanosBucketConfiguration": (
            {
                "s3:GetAccelerateConfiguration", "s3:GetBucketAcl", "s3:GetBucketCORS",
                "s3:GetBucketLocation", "s3:GetBucketLogging", "s3:GetBucketNotification",
                "s3:GetBucketObjectLockConfiguration", "s3:GetBucketOwnershipControls",
                "s3:GetBucketPolicy", "s3:GetBucketPolicyStatus", "s3:GetBucketPublicAccessBlock",
                "s3:GetBucketRequestPayment", "s3:GetBucketTagging", "s3:GetBucketVersioning",
                "s3:GetBucketWebsite", "s3:GetEncryptionConfiguration", "s3:GetLifecycleConfiguration",
                "s3:GetReplicationConfiguration", "s3:ListBucket", "s3:ListBucketVersions",
            },
            {f"arn:{partition}:s3:::{thanos_bucket}"},
            None,
        ),
        "ReadPlannedThanosRoles": (
            {
                "iam:GetRole", "iam:GetRolePolicy", "iam:ListAttachedRolePolicies",
                "iam:ListInstanceProfilesForRole", "iam:ListRolePolicies", "iam:ListRoleTags",
            },
            roles,
            None,
        ),
        "ListKmsAliasesForRefresh": ({"kms:ListAliases"}, {"*"}, None),
        "ReadTaggedProductionKmsKeys": (
            {"kms:DescribeKey", "kms:GetKeyPolicy", "kms:GetKeyRotationStatus", "kms:ListResourceTags"},
            {f"arn:{partition}:kms:{region}:{account}:key/*"},
            {
                "StringEquals": {
                    "aws:ResourceTag/Application": "thermoform",
                    "aws:ResourceTag/Environment": "production",
                }
            },
        ),
    }


def _normalize_condition(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_condition(item) for key, item in value.items()}
    if isinstance(value, list):
        return sorted(value)
    return value


def validate_role(
    *,
    role_payload: dict[str, Any],
    attached_payload: dict[str, Any],
    inline_payload: dict[str, Any],
    policy_payload: dict[str, Any],
    expected_role_arn: str,
    expected_provider_arn: str,
    github_subject: str,
    expected_policy: dict[str, tuple[set[str], set[str], dict[str, Any] | None]],
) -> None:
    role = role_payload.get("Role", {})
    _require(role.get("Arn") == expected_role_arn, "plan role ARN drifted")
    _require(role.get("MaxSessionDuration") == 3600, "plan role session duration drifted")
    _require("PermissionsBoundary" not in role, "unexpected plan role permissions boundary")
    tags = {item.get("Key"): item.get("Value") for item in role.get("Tags", [])}
    for key, value in {
        "Application": "thermoform",
        "Environment": "production",
        "AccessLevel": "plan-only",
        "ManagedBy": "cloudformation-bootstrap",
    }.items():
        _require(tags.get(key) == value, f"plan role tag drifted: {key}")

    trust = role.get("AssumeRolePolicyDocument", {})
    trust_statements = _statement_map(trust)
    _require(set(trust_statements) == {"ExactGitHubEnvironment"}, "plan role has unexpected trust statements")
    statement = trust_statements["ExactGitHubEnvironment"]
    _require(statement.get("Effect") == "Allow", "OIDC trust must allow only the exact identity")
    _require(_as_set(statement.get("Action")) == {"sts:AssumeRoleWithWebIdentity"}, "OIDC trust action drifted")
    _require(statement.get("Principal") == {"Federated": expected_provider_arn}, "OIDC trust principal drifted")
    expected_condition = {
        "StringEquals": {
            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
            "token.actions.githubusercontent.com:sub": github_subject,
        }
    }
    _require(_normalize_condition(statement.get("Condition")) == expected_condition, "OIDC trust condition drifted")

    _require(attached_payload.get("AttachedPolicies") == [], "plan role has an unexpected managed policy")
    _require(set(inline_payload.get("PolicyNames", [])) == {PLAN_POLICY_NAME}, "plan role inline policy inventory drifted")
    document = policy_payload.get("PolicyDocument")
    _require(isinstance(document, dict), "plan role inline policy is malformed")
    statements = _statement_map(document)
    _require(set(statements) == set(expected_policy), "plan role policy statement inventory drifted")
    for sid, (actions, resources, condition) in expected_policy.items():
        item = statements[sid]
        _require(item.get("Effect") == "Allow", f"plan role statement effect drifted: {sid}")
        _require(_as_set(item.get("Action")) == actions, f"plan role actions drifted: {sid}")
        _require(_as_set(item.get("Resource")) == resources, f"plan role resources drifted: {sid}")
        _require(_normalize_condition(item.get("Condition")) == _normalize_condition(condition), f"plan role condition drifted: {sid}")


def _dns_suffix(partition: str) -> str:
    return "amazonaws.com.cn" if partition == "aws-cn" else "amazonaws.com"


def validate_simulation(payload: dict[str, Any], expected: dict[str, bool]) -> None:
    results = payload.get("EvaluationResults")
    _require(isinstance(results, list), "IAM simulation results are malformed")
    actual: dict[str, bool] = {}
    for result in results:
        _require(isinstance(result, dict), "IAM simulation result is malformed")
        action = result.get("EvalActionName")
        decision = result.get("EvalDecision")
        _require(isinstance(action, str) and decision in {"allowed", "implicitDeny", "explicitDeny"}, "IAM simulation decision is malformed")
        actual[action] = decision == "allowed"
    _require(actual == expected, "IAM effective permission simulation differs from the plan-only contract")


def _simulate(
    context: AwsContext,
    role_arn: str,
    resource_arn: str,
    expected: dict[str, bool],
    *context_entries: str,
) -> None:
    arguments = [
        "--policy-source-arn", role_arn,
        "--action-names", *expected,
        "--resource-arns", resource_arn,
    ]
    if context_entries:
        arguments.extend(["--context-entries", *context_entries])
    payload = _aws_json("iam", "simulate-principal-policy", *arguments, context=context)
    validate_simulation(payload, expected)


def deployed_audit(values: argparse.Namespace) -> dict[str, Any]:
    validate_inputs(values)
    context = AwsContext(region=values.region, profile=values.profile)
    partition = validate_caller(
        _aws_json("sts", "get-caller-identity", context=context), values.account_id
    )
    stack_payload = _aws_json(
        "cloudformation", "describe-stacks", "--stack-name", values.stack_name, context=context
    )
    outputs, identities = validate_stack(stack_payload, values=values, partition=partition)
    resource_payload = _aws_json(
        "cloudformation",
        "describe-stack-resources",
        "--stack-name",
        values.stack_name,
        context=context,
    )
    resources = validate_stack_resources(
        resource_payload, create_oidc_provider=values.create_oidc_provider == "true"
    )

    owner_args = ["--bucket", values.state_bucket, "--expected-bucket-owner", values.account_id]
    location = _aws_json("s3api", "get-bucket-location", *owner_args, context=context)
    versioning = _aws_json("s3api", "get-bucket-versioning", *owner_args, context=context)
    public_access = _aws_json("s3api", "get-public-access-block", *owner_args, context=context)
    encryption = _aws_json("s3api", "get-bucket-encryption", *owner_args, context=context)
    ownership = _aws_json("s3api", "get-bucket-ownership-controls", *owner_args, context=context)
    policy_status = _aws_json("s3api", "get-bucket-policy-status", *owner_args, context=context)
    bucket_policy = _aws_json("s3api", "get-bucket-policy", *owner_args, context=context)
    bucket_tags = _aws_json("s3api", "get-bucket-tagging", *owner_args, context=context)
    bucket_lifecycle = _aws_json(
        "s3api",
        "get-bucket-lifecycle-configuration",
        *owner_args,
        context=context,
        absent_error="NoSuchLifecycleConfiguration",
    )
    kms_arn = outputs["StateKmsKeyArn"]
    validate_bucket(
        name=values.state_bucket,
        partition=partition,
        region=values.region,
        kms_arn=kms_arn,
        location=location,
        versioning=versioning,
        public_access=public_access,
        encryption=encryption,
        ownership=ownership,
        policy_status=policy_status,
        policy=bucket_policy,
        tags=bucket_tags,
        lifecycle=bucket_lifecycle,
    )

    kms_description = _aws_json("kms", "describe-key", "--key-id", kms_arn, context=context)
    kms_rotation = _aws_json("kms", "get-key-rotation-status", "--key-id", kms_arn, context=context)
    kms_tags = _aws_json("kms", "list-resource-tags", "--key-id", kms_arn, context=context)
    validate_kms(kms_description, kms_rotation, kms_tags, kms_arn)
    kms_aliases = _aws_json("kms", "list-aliases", "--key-id", kms_arn, context=context)
    validate_kms_aliases(kms_aliases, kms_arn)

    provider = _aws_json(
        "iam",
        "get-open-id-connect-provider",
        "--open-id-connect-provider-arn",
        identities["provider_arn"],
        context=context,
    )
    validate_oidc(
        provider,
        values.github_subject,
        require_managed_tags=values.create_oidc_provider == "true",
    )
    role = _aws_json("iam", "get-role", "--role-name", values.plan_role_name, context=context)
    attached = _aws_json(
        "iam", "list-attached-role-policies", "--role-name", values.plan_role_name, context=context
    )
    inline = _aws_json("iam", "list-role-policies", "--role-name", values.plan_role_name, context=context)
    policy = _aws_json(
        "iam",
        "get-role-policy",
        "--role-name",
        values.plan_role_name,
        "--policy-name",
        PLAN_POLICY_NAME,
        context=context,
    )
    expected_policy = _expected_policy(
        account=values.account_id,
        region=values.region,
        partition=partition,
        state_bucket=values.state_bucket,
        state_key=values.state_key,
        thanos_bucket=values.thanos_bucket,
        kms_arn=kms_arn,
        name_prefix=values.name_prefix,
    )
    validate_role(
        role_payload=role,
        attached_payload=attached,
        inline_payload=inline,
        policy_payload=policy,
        expected_role_arn=identities["role_arn"],
        expected_provider_arn=identities["provider_arn"],
        github_subject=values.github_subject,
        expected_policy=expected_policy,
    )

    state_arn = f"arn:{partition}:s3:::{values.state_bucket}/{values.state_key}"
    lock_arn = f"{state_arn}.tflock"
    data_bucket_arn = f"arn:{partition}:s3:::{values.thanos_bucket}"
    receive_role_arn = (
        f"arn:{partition}:iam::{values.account_id}:role/"
        f"{values.name_prefix}-thanos-receive"
    )
    _simulate(
        context,
        identities["role_arn"],
        state_arn,
        {"s3:GetObject": True, "s3:PutObject": True, "s3:DeleteObject": False},
    )
    _simulate(
        context,
        identities["role_arn"],
        lock_arn,
        {"s3:GetObject": True, "s3:PutObject": True, "s3:DeleteObject": True},
    )
    _simulate(
        context,
        identities["role_arn"],
        data_bucket_arn,
        {"s3:GetBucketVersioning": True, "s3:PutBucketPolicy": False, "s3:DeleteBucket": False},
    )
    _simulate(
        context,
        identities["role_arn"],
        receive_role_arn,
        {"iam:GetRole": True, "iam:PutRolePolicy": False, "iam:DeleteRole": False},
    )
    _simulate(
        context,
        identities["role_arn"],
        kms_arn,
        {"kms:Decrypt": True, "kms:ScheduleKeyDeletion": False},
        f"ContextKeyName=kms:CallerAccount,ContextKeyValues={values.account_id},ContextKeyType=string",
        (
            "ContextKeyName=kms:ViaService,"
            f"ContextKeyValues=s3.{values.region}.{_dns_suffix(partition)},"
            "ContextKeyType=string"
        ),
    )
    _simulate(
        context,
        identities["role_arn"],
        "*",
        {
            "cloudformation:ExecuteChangeSet": False,
            "iam:CreateRole": False,
            "kms:CreateKey": False,
        },
    )
    return {
        "account": values.account_id,
        "checks": {
            "bucket": "passed",
            "change_permissions": "denied",
            "kms": "passed",
            "oidc": "passed",
            "plan_role": "passed",
            "stack": "passed",
        },
        "mode": "deployed",
        "partition": partition,
        "region": values.region,
        "resource_count": len(resources),
        "stack": values.stack_name,
        "status": "contract-in-sync",
    }


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--stack-name", default="thermoform-production-terraform-bootstrap")
    parser.add_argument("--state-bucket", required=True)
    parser.add_argument("--state-key", default="thermal-ai/production/thanos.tfstate")
    parser.add_argument("--thanos-bucket", required=True)
    parser.add_argument("--github-subject", required=True)
    parser.add_argument("--create-oidc-provider", choices=("true", "false"), default="false")
    parser.add_argument("--plan-role-name", default="thermoform-production-plan")
    parser.add_argument("--name-prefix", default="thermoform-prod")
    parser.add_argument("--profile", help="explicit local AWS CLI profile")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    change_set = subparsers.add_parser("change-set", help="inspect one unexecuted CREATE change set")
    _add_common(change_set)
    change_set.add_argument("--change-set-name", required=True)
    change_set.add_argument(
        "--template",
        type=Path,
        default=Path("infra/aws-bootstrap/production-terraform-plan.yml"),
    )
    deployed = subparsers.add_parser("deployed", help="audit the deployed bootstrap and role")
    _add_common(deployed)
    args = parser.parse_args()
    try:
        result = change_set_audit(args) if args.mode == "change-set" else deployed_audit(args)
    except AuditError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
