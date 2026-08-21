import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
SUMMARIZER_PATH = ROOT / "scripts/summarize_terraform_plan.py"
SPEC = importlib.util.spec_from_file_location("terraform_plan_summary", SUMMARIZER_PATH)
assert SPEC and SPEC.loader
SUMMARIZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUMMARIZER)


def plan(*changes):
    return {
        "format_version": "1.2",
        "resource_changes": [
            {"address": address, "change": {"actions": actions, "after": after}}
            for address, actions, after in changes
        ],
    }


def test_summary_contains_only_addresses_and_actions():
    source = plan(
        ("module.storage.aws_s3_bucket.this", ["create"], {"secret": "never-print"}),
        ("module.storage.aws_kms_key.this", ["update"], {"policy": "sensitive-value"}),
        ("data.aws_caller_identity.current", ["read"], {"account_id": "123456789012"}),
    )

    summary = SUMMARIZER.summarize(source)
    rendered = SUMMARIZER.markdown(summary)

    assert summary["total_changes"] == 3
    assert summary["counts"] == {
        "create": 1,
        "update": 1,
        "delete": 0,
        "replace": 0,
        "read": 1,
    }
    assert "module.storage.aws_s3_bucket.this" in rendered
    assert "never-print" not in rendered
    assert "sensitive-value" not in rendered
    assert "123456789012" not in rendered


@pytest.mark.parametrize("actions", [["delete"], ["delete", "create"]])
def test_summary_rejects_destructive_actions(actions):
    source = plan(("module.storage.aws_s3_bucket.this", actions, {}))

    with pytest.raises(SUMMARIZER.PlanError, match="destructive"):
        SUMMARIZER.summarize(source)


def test_summary_rejects_oversized_plan():
    source = plan(*[(f"aws_s3_object.item[{index}]", ["create"], {}) for index in range(3)])

    with pytest.raises(SUMMARIZER.PlanError, match="limit is 2"):
        SUMMARIZER.summarize(source, max_changes=2)


def test_summary_rejects_malformed_plan():
    with pytest.raises(SUMMARIZER.PlanError, match="format_version"):
        SUMMARIZER.summarize({"resource_changes": []})

    with pytest.raises(SUMMARIZER.PlanError, match="must be a list"):
        SUMMARIZER.summarize({"format_version": "1.2", "resource_changes": {}})

    with pytest.raises(SUMMARIZER.PlanError, match="non-negative"):
        SUMMARIZER.summarize({"format_version": "1.2"}, max_changes=-1)
