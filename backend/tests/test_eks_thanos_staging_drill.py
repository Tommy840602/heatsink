from pathlib import Path
import runpy

import pytest


ROOT = Path(__file__).parents[2]
RUNTIME = runpy.run_path(str(ROOT / "scripts" / "run_eks_thanos_staging_drill.py"))
DrillError = RUNTIME["DrillError"]
select_target = RUNTIME["select_target"]
validate_confirmation = RUNTIME["validate_confirmation"]
validate_pdb = RUNTIME["validate_pdb"]


def test_drill_uses_targeted_eviction_and_guaranteed_uncordon_path():
    source = ROOT.joinpath("scripts/run_eks_thanos_staging_drill.py").read_text(
        encoding="utf-8"
    )

    assert '"apiVersion": "policy/v1"' in source
    assert '"create", "--raw"' in source
    assert "finally:" in source
    assert '"uncordon", target["node"]' in source
    assert '"drain"' not in source


def _node(name: str, zone: str):
    return {
        "metadata": {
            "name": name,
            "labels": {
                "kubernetes.io/os": "linux",
                "topology.kubernetes.io/zone": zone,
            },
        },
        "spec": {},
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    }


def _pod(ordinal: int, node: str):
    return {
        "metadata": {"name": f"thanos-receive-{ordinal}", "uid": f"uid-{ordinal}"},
        "spec": {"nodeName": node},
        "status": {"conditions": [{"type": "Ready", "status": "True"}]},
    }


def _topology(*, include_spares: bool = True):
    active_nodes = [_node(f"active-{zone}", zone) for zone in ("a", "b", "c")]
    spare_nodes = [_node(f"spare-{zone}", zone) for zone in ("a", "b", "c")] if include_spares else []
    nodes = {"items": active_nodes + spare_nodes}
    pods = {"items": [_pod(index, f"active-{zone}") for index, zone in enumerate(("a", "b", "c"))]}
    csi_nodes = {
        "items": [
            {
                "metadata": {"name": node["metadata"]["name"]},
                "spec": {"drivers": [{"name": "ebs.csi.aws.com"}]},
            }
            for node in nodes["items"]
        ]
    }
    return pods, nodes, csi_nodes


def test_drill_selects_same_zone_spare_for_one_ready_receive_pod():
    target = select_target(*_topology(), "thanos-receive-0")

    assert target == {
        "pod": "thanos-receive-0",
        "pod_uid": "uid-0",
        "node": "active-a",
        "zone": "a",
        "spare_node": "spare-a",
    }


def test_drill_rejects_zone_without_spare_capacity():
    with pytest.raises(DrillError, match="spare node"):
        select_target(*_topology(include_spares=False), "thanos-receive-0")


def test_execution_requires_exact_context_and_node_confirmation():
    with pytest.raises(DrillError, match="confirm-context"):
        validate_confirmation(
            execute=True,
            context="staging",
            node="active-a",
            confirm_context="production",
            confirm_node="active-a",
        )
    with pytest.raises(DrillError, match="confirm-node"):
        validate_confirmation(
            execute=True,
            context="staging",
            node="active-a",
            confirm_context="staging",
            confirm_node="active-b",
        )


def test_plan_mode_needs_no_mutating_confirmation():
    validate_confirmation(
        execute=False,
        context="staging",
        node="active-a",
        confirm_context=None,
        confirm_node=None,
    )


def test_drill_requires_one_pdb_disruption_and_three_healthy_replicas():
    assert validate_pdb(
        {
            "spec": {"minAvailable": 2},
            "status": {"currentHealthy": 3, "disruptionsAllowed": 1},
        }
    ) == 1

    with pytest.raises(DrillError, match="no voluntary disruption"):
        validate_pdb(
            {
                "spec": {"minAvailable": 2},
                "status": {"currentHealthy": 3, "disruptionsAllowed": 0},
            }
        )
