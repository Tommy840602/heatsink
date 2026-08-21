from pathlib import Path
import runpy

import pytest


ROOT = Path(__file__).parents[2]
RUNTIME = runpy.run_path(str(ROOT / "scripts" / "preflight_eks_thanos.py"))
PreflightError = RUNTIME["PreflightError"]
eligible_nodes = RUNTIME["eligible_nodes"]
validate_csi_nodes = RUNTIME["validate_csi_nodes"]
validate_server_version = RUNTIME["validate_server_version"]
validate_storage_class = RUNTIME["validate_storage_class"]


def _node(name: str, zone: str, *, ready: bool = True, unschedulable: bool = False):
    return {
        "metadata": {
            "name": name,
            "labels": {
                "kubernetes.io/os": "linux",
                "topology.kubernetes.io/zone": zone,
            },
        },
        "spec": {"unschedulable": unschedulable},
        "status": {
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}]
        },
    }


def _storage_class(**overrides):
    value = {
        "metadata": {"name": "thermoform-ebs-gp3"},
        "provisioner": "ebs.csi.aws.com",
        "parameters": {"type": "gp3", "encrypted": "true"},
        "reclaimPolicy": "Retain",
        "allowVolumeExpansion": True,
        "volumeBindingMode": "WaitForFirstConsumer",
    }
    value.update(overrides)
    return value


def test_preflight_accepts_three_ready_zones_and_safe_storage():
    nodes = eligible_nodes(
        {"items": [_node("node-a", "zone-a"), _node("node-b", "zone-b"), _node("node-c", "zone-c")]}
    )
    csi_nodes = {
        "items": [
            {"metadata": {"name": name}, "spec": {"drivers": [{"name": "ebs.csi.aws.com"}]}}
            for name in nodes
        ]
    }

    assert validate_server_version({"serverVersion": {"major": "1", "minor": "34+"}}) == "1.34"
    assert validate_storage_class(_storage_class()) == "thermoform-ebs-gp3"
    assert validate_csi_nodes(csi_nodes, nodes) == 3


def test_preflight_rejects_two_zone_capacity():
    with pytest.raises(PreflightError, match="three zones"):
        eligible_nodes(
            {"items": [_node("node-a", "zone-a"), _node("node-b", "zone-b"), _node("node-c", "zone-b")]}
        )


@pytest.mark.parametrize(
    "change, message",
    (
        ({"provisioner": "ebs.csi.eks.amazonaws.com"}, "standard EBS CSI"),
        ({"parameters": {"type": "gp3", "encrypted": "false"}}, "encrypt"),
        ({"reclaimPolicy": "Delete"}, "Retain"),
        ({"volumeBindingMode": "Immediate"}, "wait"),
    ),
)
def test_preflight_rejects_unsafe_storage(change, message):
    with pytest.raises(PreflightError, match=message):
        validate_storage_class(_storage_class(**change))


def test_preflight_rejects_missing_csi_registration():
    nodes = {"node-a": "zone-a", "node-b": "zone-b", "node-c": "zone-c"}
    csi_nodes = {
        "items": [
            {
                "metadata": {"name": name},
                "spec": {"drivers": [{"name": "ebs.csi.aws.com"}] if name != "node-c" else []},
            }
            for name in nodes
        ]
    }

    with pytest.raises(PreflightError, match="node-c"):
        validate_csi_nodes(csi_nodes, nodes)
