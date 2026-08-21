#!/usr/bin/env python3
"""Prove that the AWS bootstrap audit invokes only approved read APIs."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


ALLOWED_AWS_CALLS = {
    ("sts", "get-caller-identity"),
    ("cloudformation", "describe-change-set"),
    ("cloudformation", "get-template"),
    ("cloudformation", "describe-stacks"),
    ("cloudformation", "describe-stack-resources"),
    ("s3api", "get-bucket-location"),
    ("s3api", "get-bucket-versioning"),
    ("s3api", "get-public-access-block"),
    ("s3api", "get-bucket-encryption"),
    ("s3api", "get-bucket-ownership-controls"),
    ("s3api", "get-bucket-policy-status"),
    ("s3api", "get-bucket-policy"),
    ("s3api", "get-bucket-tagging"),
    ("s3api", "get-bucket-lifecycle-configuration"),
    ("kms", "describe-key"),
    ("kms", "get-key-rotation-status"),
    ("kms", "list-resource-tags"),
    ("kms", "list-aliases"),
    ("iam", "get-open-id-connect-provider"),
    ("iam", "get-role"),
    ("iam", "list-attached-role-policies"),
    ("iam", "list-role-policies"),
    ("iam", "get-role-policy"),
    ("iam", "simulate-principal-policy"),
}


class ContractError(ValueError):
    """Raised when the audit adds a mutating or unreviewed command path."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate(script_path: Path) -> None:
    source = script_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(script_path))
    calls: set[tuple[str, str]] = set()
    subprocess_calls = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "_aws_json":
                _require(len(node.args) >= 2, "_aws_json call is missing service/operation")
                service, operation = node.args[:2]
                _require(
                    isinstance(service, ast.Constant)
                    and isinstance(service.value, str)
                    and isinstance(operation, ast.Constant)
                    and isinstance(operation.value, str),
                    "AWS service and operation must be static string literals",
                )
                calls.add((service.value, operation.value))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
            and node.func.attr == "run"
        ):
            subprocess_calls += 1
            _require(
                not any(keyword.arg == "shell" for keyword in node.keywords),
                "AWS audit must not invoke a shell",
            )

    _require(calls == ALLOWED_AWS_CALLS, f"AWS audit command inventory drifted: {sorted(calls ^ ALLOWED_AWS_CALLS)}")
    _require(subprocess_calls == 1, "all process execution must remain inside one guarded runner")
    _require('command = ["aws", service, operation' in source, "guarded runner must invoke only AWS CLI")
    for forbidden in (
        '"create-change-set"',
        '"execute-change-set"',
        '"delete-stack"',
        '"update-stack"',
        '"detect-stack-drift"',
        '"put-bucket',
        '"create-role"',
        '"update-role"',
        '"delete-role"',
    ):
        _require(forbidden not in source, f"mutating AWS command token found: {forbidden}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    args = parser.parse_args()
    try:
        validate(args.script)
    except (OSError, SyntaxError, ContractError) as exc:
        parser.error(str(exc))
    print("AWS bootstrap audit read-only contract is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
