import argparse
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
VALIDATOR_PATH = ROOT / "scripts" / "validate_self_hosted_stack.py"
SPEC = importlib.util.spec_from_file_location("self_hosted_validator", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def _args():
    return argparse.Namespace(
        rook_cluster=None, openbao=None, openbao_csi=None, harbor=None
    )


def test_self_hosted_contract_is_valid():
    VALIDATOR.validate(ROOT, _args())


def test_rejects_ceph_claiming_every_disk():
    values = ROOT.joinpath("infra/self-hosted/helm/rook-cluster-values.yaml").read_text()
    changed = values.replace("useAllDevices: false", "useAllDevices: true")

    with pytest.raises(VALIDATOR.ContractError, match="useAllDevices"):
        VALIDATOR._contains_all(changed, ("useAllDevices: false",), "Rook cluster values")


def test_rejects_static_harbor_admin_password():
    values = ROOT.joinpath("infra/self-hosted/helm/harbor-values.yaml").read_text()
    changed = values + '\nharborAdminPassword: "forbidden"\n'

    assert "harborAdminPassword:" in changed
    with pytest.raises(VALIDATOR.ContractError, match="unsafe Harbor"):
        for forbidden in ("harborAdminPassword:", "accesskey:", "secretkey:"):
            VALIDATOR._require(forbidden not in changed, f"unsafe Harbor value: {forbidden}")


def test_rejects_writable_thanos_secret_files():
    providers = ROOT.joinpath(
        "infra/kubernetes/overlays/rke2-ceph-openbao/secret-provider-classes.yaml"
    ).read_text()
    changed = providers.replace("filePermission: 0400", "filePermission: 0644", 1)

    with pytest.raises(VALIDATOR.ContractError, match="owner-read-only"):
        VALIDATOR._require(
            changed.count("filePermission: 0400") == 3,
            "Thanos secret files must be owner-read-only",
        )
