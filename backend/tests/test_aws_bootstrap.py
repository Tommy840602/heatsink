import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
TEMPLATE = ROOT / "infra/aws-bootstrap/production-terraform-plan.yml"
VALIDATOR_PATH = ROOT / "scripts/validate_aws_bootstrap.py"
SPEC = importlib.util.spec_from_file_location("aws_bootstrap_validator", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def candidate(tmp_path, replace_from, replace_to):
    path = tmp_path / "bootstrap.yml"
    path.write_text(
        TEMPLATE.read_text(encoding="utf-8").replace(replace_from, replace_to, 1),
        encoding="utf-8",
    )
    return path


def test_aws_bootstrap_contract_is_valid():
    VALIDATOR.validate(TEMPLATE)


def test_contract_rejects_wildcard_oidc_trust(tmp_path):
    path = candidate(
        tmp_path,
        "              StringEquals:\n                token.actions.githubusercontent.com:aud:",
        "              StringLike:\n                token.actions.githubusercontent.com:aud:",
    )

    with pytest.raises(VALIDATOR.ContractError, match="exact equality"):
        VALIDATOR.validate(path)


def test_contract_rejects_weakened_subject_constraint(tmp_path):
    path = candidate(
        tmp_path,
        "^repo:[A-Za-z0-9_.-]+(@[0-9]+)?/[A-Za-z0-9_.-]+(@[0-9]+)?:environment:production-plan$",
        "^repo:.*:environment:production-plan$",
    )

    with pytest.raises(VALIDATOR.ContractError, match="subject constraint"):
        VALIDATOR.validate(path)


def test_contract_rejects_state_delete_permission(tmp_path):
    path = candidate(
        tmp_path,
        "                  - s3:GetObjectVersion\n                  - s3:PutObject",
        "                  - s3:GetObjectVersion\n                  - s3:DeleteObject\n                  - s3:PutObject",
    )

    with pytest.raises(VALIDATOR.ContractError, match="must not delete the state"):
        VALIDATOR.validate(path)


def test_contract_rejects_unretained_bucket_policy(tmp_path):
    path = candidate(
        tmp_path,
        "  StateBucketPolicy:\n    Type: AWS::S3::BucketPolicy\n    DeletionPolicy: Retain",
        "  StateBucketPolicy:\n    Type: AWS::S3::BucketPolicy\n    DeletionPolicy: Delete",
    )

    with pytest.raises(VALIDATOR.ContractError, match="bucket policy must be retained"):
        VALIDATOR.validate(path)


def test_contract_rejects_infrastructure_mutation(tmp_path):
    path = candidate(
        tmp_path,
        "                  - iam:GetRole\n",
        "                  - iam:CreateRole\n                  - iam:GetRole\n",
    )

    with pytest.raises(VALIDATOR.ContractError, match="mutating infrastructure"):
        VALIDATOR.validate(path)
