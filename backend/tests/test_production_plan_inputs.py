import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
VALIDATOR_PATH = ROOT / "scripts/validate_production_plan_inputs.py"
SPEC = importlib.util.spec_from_file_location("production_plan_inputs", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)

SHA = "a" * 40


def valid_values():
    return {
        "CONFIRMATION": "PLAN_ONLY",
        "EXPECTED_COMMIT_SHA": SHA,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": SHA,
        "AWS_ACCOUNT_ID": "123456789012",
        "AWS_REGION": "ap-northeast-1",
        "TERRAFORM_PLAN_ROLE_ARN": "arn:aws:iam::123456789012:role/thermoform-production-plan",
        "TF_STATE_BUCKET": "thermoform-production-state-123456789012",
        "TF_STATE_KEY": "thermal-ai/production/thanos.tfstate",
        "THANOS_BUCKET_NAME": "thermoform-production-thanos-123456789012",
        "THANOS_OBJECT_PREFIX": "thermoform/metrics",
        "EKS_OIDC_PROVIDER_ARN": (
            "arn:aws:iam::123456789012:oidc-provider/"
            "oidc.eks.ap-northeast-1.amazonaws.com/id/ABC123"
        ),
        "EKS_OIDC_ISSUER_URL": (
            "https://oidc.eks.ap-northeast-1.amazonaws.com/id/ABC123"
        ),
    }


def test_valid_production_inputs_return_value_free_summary():
    result = VALIDATOR.validate(valid_values())

    assert result == {
        "account": "123456789012",
        "commit": SHA,
        "environment": "production-plan",
        "region": "ap-northeast-1",
        "state_key": "thermal-ai/production/thanos.tfstate",
        "status": "validated",
    }
    assert "role" not in result
    assert "bucket" not in result


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("CONFIRMATION", "APPLY", "PLAN_ONLY"),
        ("GITHUB_REF", "refs/heads/feature", "main"),
        ("EXPECTED_COMMIT_SHA", "b" * 40, "exactly match"),
        ("AWS_ACCOUNT_ID", "000000000000", "account"),
        ("TERRAFORM_PLAN_ROLE_ARN", "arn:aws:iam::999999999999:role/plan", "wrong account"),
        ("TF_STATE_KEY", "../production.tfstate", "safe relative"),
        ("THANOS_OBJECT_PREFIX", "thermoform//metrics", "prefix"),
        (
            "EKS_OIDC_ISSUER_URL",
            "https://oidc.eks.us-east-1.amazonaws.com/id/ABC123",
            "do not match",
        ),
    ],
)
def test_production_inputs_fail_closed(key, value, message):
    values = valid_values()
    values[key] = value

    with pytest.raises(VALIDATOR.InputError, match=message):
        VALIDATOR.validate(values)


def test_state_and_data_buckets_must_be_distinct():
    values = valid_values()
    values["TF_STATE_BUCKET"] = values["THANOS_BUCKET_NAME"]

    with pytest.raises(VALIDATOR.InputError, match="different buckets"):
        VALIDATOR.validate(values)
