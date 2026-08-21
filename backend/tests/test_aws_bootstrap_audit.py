import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).parents[2]
AUDIT_PATH = ROOT / "scripts/audit_aws_bootstrap.py"
TEMPLATE = ROOT / "infra/aws-bootstrap/production-terraform-plan.yml"
SPEC = importlib.util.spec_from_file_location("aws_bootstrap_audit", AUDIT_PATH)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)

ACCOUNT = "123456789012"
REGION = "ap-northeast-1"
STATE_BUCKET = "thermoform-production-state-123456789012"
STATE_KEY = "thermal-ai/production/thanos.tfstate"
THANOS_BUCKET = "thermoform-production-thanos-123456789012"
SUBJECT = (
    "repo:Tommy840602@84989346/heatsink@1341254721:"
    "environment:production-plan"
)
STACK = "thermoform-production-terraform-bootstrap"
CHANGE_SET = "bootstrap-reviewed"
ROLE_NAME = "thermoform-production-plan"
NAME_PREFIX = "thermoform-prod"
KMS_ARN = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/11111111-2222-3333-4444-555555555555"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}"
PROVIDER_ARN = (
    f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"
)


def values(**overrides):
    result = {
        "account_id": ACCOUNT,
        "region": REGION,
        "stack_name": STACK,
        "state_bucket": STATE_BUCKET,
        "state_key": STATE_KEY,
        "thanos_bucket": THANOS_BUCKET,
        "github_subject": SUBJECT,
        "create_oidc_provider": "false",
        "plan_role_name": ROLE_NAME,
        "name_prefix": NAME_PREFIX,
        "profile": None,
        "change_set_name": CHANGE_SET,
        "template": TEMPLATE,
    }
    result.update(overrides)
    return SimpleNamespace(**result)


def expected_parameters(create="false"):
    return {
        "StateBucketName": STATE_BUCKET,
        "StateKey": STATE_KEY,
        "ThanosBucketName": THANOS_BUCKET,
        "GitHubOidcSubject": SUBJECT,
        "CreateGitHubOidcProvider": create,
        "PlanRoleName": ROLE_NAME,
        "TerraformNamePrefix": NAME_PREFIX,
    }


def parameter_list(create="false"):
    return [
        {"ParameterKey": key, "ParameterValue": value}
        for key, value in expected_parameters(create).items()
    ]


def change_set_payload(create="false"):
    resources = dict(AUDIT.BASE_RESOURCES)
    if create == "true":
        resources.update(AUDIT.OIDC_RESOURCE)
    return {
        "StackName": STACK,
        "ChangeSetName": CHANGE_SET,
        "ChangeSetType": "CREATE",
        "Status": "CREATE_COMPLETE",
        "ExecutionStatus": "AVAILABLE",
        "Capabilities": ["CAPABILITY_NAMED_IAM"],
        "Parameters": parameter_list(create),
        "Changes": [
            {
                "Type": "Resource",
                "ResourceChange": {
                    "Action": "Add",
                    "LogicalResourceId": logical_id,
                    "ResourceType": resource_type,
                    "Replacement": None,
                },
            }
            for logical_id, resource_type in resources.items()
        ],
    }


def stack_payload(create="false"):
    return {
        "Stacks": [
            {
                "StackName": STACK,
                "StackStatus": "CREATE_COMPLETE",
                "EnableTerminationProtection": True,
                "Capabilities": ["CAPABILITY_NAMED_IAM"],
                "Parameters": parameter_list(create),
                "Outputs": [
                    {"OutputKey": "StateBucketName", "OutputValue": STATE_BUCKET},
                    {"OutputKey": "StateKey", "OutputValue": STATE_KEY},
                    {"OutputKey": "StateKmsKeyArn", "OutputValue": KMS_ARN},
                    {"OutputKey": "TerraformPlanRoleArn", "OutputValue": ROLE_ARN},
                    {"OutputKey": "GitHubOidcProviderArn", "OutputValue": PROVIDER_ARN},
                ],
            }
        ]
    }


def policy_document():
    expected = AUDIT._expected_policy(
        account=ACCOUNT,
        region=REGION,
        partition="aws",
        state_bucket=STATE_BUCKET,
        state_key=STATE_KEY,
        thanos_bucket=THANOS_BUCKET,
        kms_arn=KMS_ARN,
        name_prefix=NAME_PREFIX,
    )
    statements = []
    for sid, (actions, resources, condition) in expected.items():
        statement = {
            "Sid": sid,
            "Effect": "Allow",
            "Action": sorted(actions),
            "Resource": sorted(resources),
        }
        if condition is not None:
            statement["Condition"] = copy.deepcopy(condition)
        statements.append(statement)
    return {"Version": "2012-10-17", "Statement": statements}, expected


def role_payload():
    return {
        "Role": {
            "Arn": ROLE_ARN,
            "MaxSessionDuration": 3600,
            "AssumeRolePolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "ExactGitHubEnvironment",
                        "Effect": "Allow",
                        "Principal": {"Federated": PROVIDER_ARN},
                        "Action": "sts:AssumeRoleWithWebIdentity",
                        "Condition": {
                            "StringEquals": {
                                "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                                "token.actions.githubusercontent.com:sub": SUBJECT,
                            }
                        },
                    }
                ],
            },
            "Tags": [
                {"Key": "Application", "Value": "thermoform"},
                {"Key": "Environment", "Value": "production"},
                {"Key": "AccessLevel", "Value": "plan-only"},
                {"Key": "ManagedBy", "Value": "cloudformation-bootstrap"},
            ],
        }
    }


def bucket_arguments():
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyInsecureTransport",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:*",
                "Resource": [
                    f"arn:aws:s3:::{STATE_BUCKET}",
                    f"arn:aws:s3:::{STATE_BUCKET}/*",
                ],
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            }
        ],
    }
    return {
        "name": STATE_BUCKET,
        "partition": "aws",
        "region": REGION,
        "kms_arn": KMS_ARN,
        "location": {"LocationConstraint": REGION},
        "versioning": {"Status": "Enabled"},
        "public_access": {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }
        },
        "encryption": {
            "ServerSideEncryptionConfiguration": {
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": "aws:kms",
                            "KMSMasterKeyID": KMS_ARN,
                        },
                        "BucketKeyEnabled": False,
                    }
                ]
            }
        },
        "ownership": {
            "OwnershipControls": {
                "Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]
            }
        },
        "policy_status": {"PolicyStatus": {"IsPublic": False}},
        "policy": {"Policy": policy},
        "tags": {
            "TagSet": [
                {"Key": "Application", "Value": "thermoform"},
                {"Key": "Environment", "Value": "production"},
                {"Key": "DataClassification", "Value": "terraform-state"},
                {"Key": "ManagedBy", "Value": "cloudformation-bootstrap"},
            ]
        },
        "lifecycle": {},
    }


def test_inputs_accept_exact_immutable_subject_and_reject_bucket_collision():
    AUDIT.validate_inputs(values())

    with pytest.raises(AUDIT.AuditError, match="must differ"):
        AUDIT.validate_inputs(values(thanos_bucket=STATE_BUCKET))


def test_change_set_accepts_only_exact_create_inventory():
    summary = AUDIT.validate_change_set(
        change_set_payload(),
        stack_name=STACK,
        change_set_name=CHANGE_SET,
        parameters=expected_parameters(),
        create_oidc_provider=False,
    )

    assert len(summary) == 5
    assert {item["action"] for item in summary} == {"Add"}


def test_change_set_rejects_modify_replacement_and_parameter_drift():
    modified = change_set_payload()
    modified["Changes"][0]["ResourceChange"]["Action"] = "Modify"
    with pytest.raises(AUDIT.AuditError, match="only add"):
        AUDIT.validate_change_set(
            modified,
            stack_name=STACK,
            change_set_name=CHANGE_SET,
            parameters=expected_parameters(),
            create_oidc_provider=False,
        )

    replacement = change_set_payload()
    replacement["Changes"][0]["ResourceChange"]["Replacement"] = "True"
    with pytest.raises(AUDIT.AuditError, match="replacement"):
        AUDIT.validate_change_set(
            replacement,
            stack_name=STACK,
            change_set_name=CHANGE_SET,
            parameters=expected_parameters(),
            create_oidc_provider=False,
        )

    drifted = change_set_payload()
    drifted["Parameters"][0]["ParameterValue"] = "wrong-bucket"
    with pytest.raises(AUDIT.AuditError, match="parameters"):
        AUDIT.validate_change_set(
            drifted,
            stack_name=STACK,
            change_set_name=CHANGE_SET,
            parameters=expected_parameters(),
            create_oidc_provider=False,
        )


def test_template_hash_rejects_unreviewed_change():
    reviewed = TEMPLATE.read_text(encoding="utf-8")
    digest = AUDIT.validate_template({"TemplateBody": reviewed}, reviewed)
    assert len(digest) == 64

    with pytest.raises(AUDIT.AuditError, match="differs"):
        AUDIT.validate_template({"TemplateBody": reviewed + "\n# drift"}, reviewed)


def test_stack_requires_exact_outputs_and_termination_protection():
    outputs, identities = AUDIT.validate_stack(
        stack_payload(), values=values(), partition="aws"
    )
    assert outputs["StateKmsKeyArn"] == KMS_ARN
    assert identities == {"provider_arn": PROVIDER_ARN, "role_arn": ROLE_ARN}

    unprotected = stack_payload()
    unprotected["Stacks"][0]["EnableTerminationProtection"] = False
    with pytest.raises(AUDIT.AuditError, match="termination protection"):
        AUDIT.validate_stack(unprotected, values=values(), partition="aws")


def test_stack_resource_inventory_honors_optional_oidc_provider():
    resources = dict(AUDIT.BASE_RESOURCES)
    payload = {
        "StackResources": [
            {
                "LogicalResourceId": logical_id,
                "ResourceType": resource_type,
                "ResourceStatus": "CREATE_COMPLETE",
            }
            for logical_id, resource_type in resources.items()
        ]
    }
    assert AUDIT.validate_stack_resources(payload, create_oidc_provider=False) == resources

    with pytest.raises(AUDIT.AuditError, match="inventory"):
        AUDIT.validate_stack_resources(payload, create_oidc_provider=True)


def test_bucket_contract_rejects_public_access_and_state_expiration():
    AUDIT.validate_bucket(**bucket_arguments())

    public = bucket_arguments()
    public["policy_status"]["PolicyStatus"]["IsPublic"] = True
    with pytest.raises(AUDIT.AuditError, match="public"):
        AUDIT.validate_bucket(**public)

    expiring = bucket_arguments()
    expiring["lifecycle"] = {
        "Rules": [{"Status": "Enabled", "NoncurrentVersionExpiration": {"NoncurrentDays": 30}}]
    }
    with pytest.raises(AUDIT.AuditError, match="may not expire"):
        AUDIT.validate_bucket(**expiring)


def test_kms_and_alias_contracts_are_exact():
    description = {
        "KeyMetadata": {
            "Arn": KMS_ARN,
            "Enabled": True,
            "KeyState": "Enabled",
            "KeyUsage": "ENCRYPT_DECRYPT",
            "KeySpec": "SYMMETRIC_DEFAULT",
            "MultiRegion": False,
        }
    }
    tags = {
        "Tags": [
            {"TagKey": "Application", "TagValue": "thermoform"},
            {"TagKey": "Environment", "TagValue": "production"},
            {"TagKey": "ManagedBy", "TagValue": "cloudformation-bootstrap"},
        ]
    }
    AUDIT.validate_kms(description, {"KeyRotationEnabled": True}, tags, KMS_ARN)
    AUDIT.validate_kms_aliases(
        {
            "Aliases": [
                {
                    "AliasName": "alias/thermoform-production-terraform-state",
                    "TargetKeyId": KMS_ARN.rsplit("/", 1)[1],
                }
            ]
        },
        KMS_ARN,
    )

    with pytest.raises(AUDIT.AuditError, match="rotation"):
        AUDIT.validate_kms(description, {"KeyRotationEnabled": False}, tags, KMS_ARN)


def test_oidc_contract_allows_preexisting_provider_without_stack_tags():
    payload = {
        "Url": "token.actions.githubusercontent.com",
        "ClientIDList": ["sts.amazonaws.com"],
        "ThumbprintList": ["a" * 40],
        "Tags": [],
    }
    AUDIT.validate_oidc(payload, SUBJECT, require_managed_tags=False)

    with pytest.raises(AUDIT.AuditError, match="Application tag"):
        AUDIT.validate_oidc(payload, SUBJECT, require_managed_tags=True)


def test_role_policy_and_trust_are_exact():
    document, expected = policy_document()
    AUDIT.validate_role(
        role_payload=role_payload(),
        attached_payload={"AttachedPolicies": []},
        inline_payload={"PolicyNames": [AUDIT.PLAN_POLICY_NAME]},
        policy_payload={"PolicyDocument": document},
        expected_role_arn=ROLE_ARN,
        expected_provider_arn=PROVIDER_ARN,
        github_subject=SUBJECT,
        expected_policy=expected,
    )

    widened = copy.deepcopy(document)
    widened["Statement"][0]["Action"].append("s3:DeleteBucket")
    with pytest.raises(AUDIT.AuditError, match="actions drifted"):
        AUDIT.validate_role(
            role_payload=role_payload(),
            attached_payload={"AttachedPolicies": []},
            inline_payload={"PolicyNames": [AUDIT.PLAN_POLICY_NAME]},
            policy_payload={"PolicyDocument": widened},
            expected_role_arn=ROLE_ARN,
            expected_provider_arn=PROVIDER_ARN,
            github_subject=SUBJECT,
            expected_policy=expected,
        )


def test_role_rejects_wildcard_trust_and_managed_policy():
    document, expected = policy_document()
    wildcard = role_payload()
    trust = wildcard["Role"]["AssumeRolePolicyDocument"]["Statement"][0]
    trust["Condition"] = {
        "StringLike": {"token.actions.githubusercontent.com:sub": "repo:*"}
    }
    with pytest.raises(AUDIT.AuditError, match="trust condition"):
        AUDIT.validate_role(
            role_payload=wildcard,
            attached_payload={"AttachedPolicies": []},
            inline_payload={"PolicyNames": [AUDIT.PLAN_POLICY_NAME]},
            policy_payload={"PolicyDocument": document},
            expected_role_arn=ROLE_ARN,
            expected_provider_arn=PROVIDER_ARN,
            github_subject=SUBJECT,
            expected_policy=expected,
        )

    with pytest.raises(AUDIT.AuditError, match="managed policy"):
        AUDIT.validate_role(
            role_payload=role_payload(),
            attached_payload={"AttachedPolicies": [{"PolicyArn": "arn:aws:iam::aws:policy/AdministratorAccess"}]},
            inline_payload={"PolicyNames": [AUDIT.PLAN_POLICY_NAME]},
            policy_payload={"PolicyDocument": document},
            expected_role_arn=ROLE_ARN,
            expected_provider_arn=PROVIDER_ARN,
            github_subject=SUBJECT,
            expected_policy=expected,
        )


def test_simulator_must_match_allowed_and_denied_decisions():
    payload = {
        "EvaluationResults": [
            {"EvalActionName": "s3:GetObject", "EvalDecision": "allowed"},
            {"EvalActionName": "s3:DeleteObject", "EvalDecision": "implicitDeny"},
        ]
    }
    AUDIT.validate_simulation(
        payload, {"s3:GetObject": True, "s3:DeleteObject": False}
    )

    payload["EvaluationResults"][1]["EvalDecision"] = "allowed"
    with pytest.raises(AUDIT.AuditError, match="simulation differs"):
        AUDIT.validate_simulation(
            payload, {"s3:GetObject": True, "s3:DeleteObject": False}
        )
