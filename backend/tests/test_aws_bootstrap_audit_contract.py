import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
AUDIT_PATH = ROOT / "scripts/audit_aws_bootstrap.py"
VALIDATOR_PATH = ROOT / "scripts/validate_aws_bootstrap_audit.py"
SPEC = importlib.util.spec_from_file_location("aws_bootstrap_audit_contract", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def test_aws_bootstrap_audit_is_read_only():
    VALIDATOR.validate(AUDIT_PATH)


def test_contract_rejects_mutating_aws_call(tmp_path):
    candidate = tmp_path / "audit.py"
    candidate.write_text(
        AUDIT_PATH.read_text(encoding="utf-8").replace(
            '"cloudformation", "describe-stacks"',
            '"cloudformation", "delete-stack"',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(VALIDATOR.ContractError, match="command inventory"):
        VALIDATOR.validate(candidate)


def test_contract_rejects_shell_execution(tmp_path):
    candidate = tmp_path / "audit.py"
    candidate.write_text(
        AUDIT_PATH.read_text(encoding="utf-8").replace(
            "            timeout=30,\n",
            "            timeout=30,\n            shell=True,\n",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(VALIDATOR.ContractError, match="must not invoke a shell"):
        VALIDATOR.validate(candidate)
