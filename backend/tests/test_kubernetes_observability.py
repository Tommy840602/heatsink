import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
VALIDATOR_PATH = ROOT / "scripts" / "validate_kubernetes_observability.py"
SPEC = importlib.util.spec_from_file_location("kubernetes_validator", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
pytestmark = pytest.mark.skipif(
    shutil.which("kubectl") is None,
    reason="kubectl is required to render the Kustomize contract",
)


def _render() -> str:
    return subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "infra/kubernetes/observability")],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _render_eks(tmp_path: Path) -> str:
    template = tmp_path / "eks-template.yml"
    manifest = tmp_path / "eks.yml"
    template.write_text(
        subprocess.run(
            ["kubectl", "kustomize", str(ROOT / "infra/kubernetes/overlays/aws-eks")],
            check=True,
            capture_output=True,
            text=True,
        ).stdout,
        encoding="utf-8",
    )
    subprocess.run(
        [
            "python",
            str(ROOT / "scripts/render_eks_thanos_manifest.py"),
            "--template",
            str(template),
            "--receive-role-arn",
            "arn:aws:iam::123456789012:role/thermoform-receive",
            "--store-role-arn",
            "arn:aws:iam::123456789012:role/thermoform-store",
            "--compact-role-arn",
            "arn:aws:iam::123456789012:role/thermoform-compact",
            "--output",
            str(manifest),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return manifest.read_text(encoding="utf-8")


def test_rendered_kubernetes_observability_contract_is_valid():
    VALIDATOR.validate(_render())


def test_contract_rejects_receive_replication_drift():
    manifest = _render().replace("--receive.replication-factor=3", "--receive.replication-factor=2")

    with pytest.raises(VALIDATOR.ContractError, match="replication factor"):
        VALIDATOR.validate(manifest)


def test_contract_rejects_embedded_static_credentials():
    manifest = _render() + "\naccess_key: forbidden\n"

    with pytest.raises(VALIDATOR.ContractError, match="access_key"):
        VALIDATOR.validate(manifest)


def test_rendered_eks_contract_is_valid(tmp_path):
    VALIDATOR.validate(_render_eks(tmp_path))


def test_eks_contract_rejects_unencrypted_ebs(tmp_path):
    manifest = _render_eks(tmp_path).replace('encrypted: "true"', 'encrypted: "false"')

    with pytest.raises(VALIDATOR.ContractError, match="encrypted"):
        VALIDATOR.validate(manifest)
