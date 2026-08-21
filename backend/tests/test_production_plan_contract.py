import importlib.util
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).parents[2]
TF_ROOT = ROOT / "infra/terraform/environments/production"
WORKFLOW = ROOT / ".github/workflows/terraform-production-plan.yml"
VALIDATOR_PATH = ROOT / "scripts/validate_production_plan_contract.py"
SPEC = importlib.util.spec_from_file_location("production_plan_contract", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def test_production_plan_contract_is_valid():
    VALIDATOR.validate(TF_ROOT, WORKFLOW)


def test_contract_rejects_apply_path(tmp_path):
    candidate_root = tmp_path / "production"
    shutil.copytree(TF_ROOT, candidate_root)
    candidate_workflow = tmp_path / "workflow.yml"
    content = WORKFLOW.read_text(encoding="utf-8")
    candidate_workflow.write_text(content + "\n# terraform apply\n", encoding="utf-8")

    with pytest.raises(VALIDATOR.ContractError, match="must not apply"):
        VALIDATOR.validate(candidate_root, candidate_workflow)


def test_contract_rejects_account_guard_removal(tmp_path):
    candidate_root = tmp_path / "production"
    shutil.copytree(TF_ROOT, candidate_root)
    provider = candidate_root / "providers.tf"
    provider.write_text(
        provider.read_text(encoding="utf-8").replace(
            "  allowed_account_ids = [var.expected_aws_account_id]\n", ""
        ),
        encoding="utf-8",
    )

    with pytest.raises(VALIDATOR.ContractError, match="expected account"):
        VALIDATOR.validate(candidate_root, WORKFLOW)
