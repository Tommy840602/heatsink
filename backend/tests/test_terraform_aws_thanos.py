import importlib.util
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).parents[2]
MODULE = ROOT / "infra/terraform/modules/aws-thanos-storage"
VALIDATOR_PATH = ROOT / "scripts/validate_terraform_thanos.py"
SPEC = importlib.util.spec_from_file_location("terraform_thanos_validator", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def test_terraform_thanos_safety_contract_is_valid():
    VALIDATOR.validate(MODULE)

    gitignore = ROOT.joinpath(".gitignore").read_text(encoding="utf-8")
    assert "**/.terraform/*" in gitignore
    assert "*.tfstate.*" in gitignore
    assert "*.tfplan" in gitignore
    assert ".terraform.lock.hcl" not in gitignore


def test_contract_rejects_receive_delete_permission(tmp_path):
    candidate = tmp_path / "module"
    shutil.copytree(MODULE, candidate)
    main = candidate.joinpath("main.tf")
    content = main.read_text(encoding="utf-8")
    content = content.replace(
        'receive = [\n      "s3:AbortMultipartUpload",',
        'receive = [\n      "s3:DeleteObject",\n      "s3:AbortMultipartUpload",',
        1,
    )
    main.write_text(content, encoding="utf-8")

    with pytest.raises(VALIDATOR.ContractError, match="only one workload"):
        VALIDATOR.validate(candidate)


def test_contract_rejects_current_object_expiration(tmp_path):
    candidate = tmp_path / "module"
    shutil.copytree(MODULE, candidate)
    main = candidate.joinpath("main.tf")
    content = main.read_text(encoding="utf-8").replace(
        "    noncurrent_version_expiration {",
        "    expiration {\n      days = 30\n    }\n\n    noncurrent_version_expiration {",
    )
    main.write_text(content, encoding="utf-8")

    with pytest.raises(VALIDATOR.ContractError, match="current Thanos objects"):
        VALIDATOR.validate(candidate)
