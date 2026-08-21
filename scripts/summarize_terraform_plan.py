#!/usr/bin/env python3
"""Emit a value-free Terraform plan summary and reject destructive changes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class PlanError(ValueError):
    """Raised when a plan is malformed, oversized, or destructive."""


def summarize(plan: dict[str, Any], *, max_changes: int = 50) -> dict[str, Any]:
    if not isinstance(plan.get("format_version"), str):
        raise PlanError("Terraform plan JSON has no format_version")
    if not isinstance(max_changes, int) or max_changes < 0:
        raise PlanError("max_changes must be a non-negative integer")
    resources = plan.get("resource_changes", [])
    if not isinstance(resources, list):
        raise PlanError("Terraform resource_changes must be a list")
    changes: list[dict[str, str]] = []
    counts = {"create": 0, "update": 0, "delete": 0, "replace": 0, "read": 0}
    for resource in resources:
        if not isinstance(resource, dict):
            raise PlanError("Terraform resource change is malformed")
        address = resource.get("address")
        change = resource.get("change")
        if not isinstance(change, dict):
            raise PlanError("Terraform resource change is malformed")
        actions = change.get("actions")
        if not isinstance(address, str) or not isinstance(actions, list):
            raise PlanError("Terraform resource change is malformed")
        if actions == ["no-op"]:
            continue
        if "delete" in actions and "create" in actions:
            action = "replace"
        elif "delete" in actions:
            action = "delete"
        elif "create" in actions:
            action = "create"
        elif "update" in actions:
            action = "update"
        elif "read" in actions:
            action = "read"
        else:
            raise PlanError(f"unsupported actions for {address}: {actions}")
        counts[action] += 1
        changes.append({"address": address, "action": action})

    if len(changes) > max_changes:
        raise PlanError(f"plan changes {len(changes)} resources; limit is {max_changes}")
    destructive = [item["address"] for item in changes if item["action"] in {"delete", "replace"}]
    if destructive:
        raise PlanError("destructive production plan: " + ", ".join(destructive))
    return {"counts": counts, "changes": changes, "total_changes": len(changes)}


def markdown(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    lines = [
        "## Production Terraform plan",
        "",
        "Plan-only guard passed. No delete or replacement action is present.",
        "",
        "| Create | Update | Read | Delete | Replace | Total |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| {counts['create']} | {counts['update']} | {counts['read']} | "
            f"{counts['delete']} | {counts['replace']} | {summary['total_changes']} |"
        ),
    ]
    if summary["changes"]:
        lines.extend(["", "### Resource actions", ""])
        lines.extend(
            f"- `{item['address']}` — {item['action']}" for item in summary["changes"]
        )
    else:
        lines.extend(["", "No infrastructure changes."])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan_json", type=Path)
    parser.add_argument("--max-changes", type=int, default=50)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        summary = summarize(
            json.loads(args.plan_json.read_text(encoding="utf-8")),
            max_changes=args.max_changes,
        )
    except (OSError, json.JSONDecodeError, PlanError) as exc:
        parser.error(str(exc))
    rendered = markdown(summary)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
