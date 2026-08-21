#!/usr/bin/env python3
"""Validate the credential-free production Terraform plan contract."""

from __future__ import annotations

import argparse
from pathlib import Path
import re


CHECKOUT_SHA = "11d5960a326750d5838078e36cf38b85af677262"
AWS_CREDENTIALS_SHA = "e6de054238d6b7531b4efff3b6587d9aade6a06c"
SETUP_TERRAFORM_SHA = "dfe3c3f87815947d99a8997f908cb6525fc44e9e"


class ContractError(ValueError):
    """Raised when the production root or plan workflow becomes unsafe."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate(root: Path, workflow_path: Path) -> None:
    backend = root.joinpath("backend.tf").read_text(encoding="utf-8")
    providers = root.joinpath("providers.tf").read_text(encoding="utf-8")
    versions = root.joinpath("versions.tf").read_text(encoding="utf-8")
    main = root.joinpath("main.tf").read_text(encoding="utf-8")
    lock = root.joinpath(".terraform.lock.hcl").read_text(encoding="utf-8")
    workflow = workflow_path.read_text(encoding="utf-8")
    combined = "\n".join((backend, providers, versions, main, lock, workflow))

    _require('backend "s3"' in backend, "production state must use the S3 backend")
    _require("encrypt      = true" in backend, "S3 backend encryption must be enabled")
    _require("use_lockfile = true" in backend, "S3 native state locking must be enabled")
    _require("dynamodb" not in backend.lower(), "deprecated DynamoDB locking must not be used")
    _require(
        "allowed_account_ids = [var.expected_aws_account_id]" in providers,
        "AWS provider must fail closed on the expected account",
    )
    _require(
        'required_version = ">= 1.15.0, < 1.16.0"' in versions,
        "Terraform minor version must be bounded",
    )
    _require('version = "= 6.55.0"' in versions, "AWS provider must be exactly pinned")
    _require('source = "../../modules/aws-thanos-storage"' in main, "unexpected module source")
    _require('version     = "6.55.0"' in lock, "dependency lock must pin AWS 6.55.0")
    _require(lock.count("zh:") >= 10, "dependency lock is missing signed package hashes")
    _require(not root.joinpath("terraform.tfvars").exists(), "real production tfvars must not be committed")

    _require(re.search(r"(?m)^\s*workflow_dispatch:\s*$", workflow) is not None, "plan must be manual")
    _require(re.search(r"(?m)^\s*(push|pull_request):\s*$", workflow) is None, "plan must not run on push or pull request")
    _require("environment: production-plan" in workflow, "GitHub production-plan Environment is required")
    _require("id-token: write" in workflow, "OIDC permission is required")
    _require("contents: read" in workflow, "repository permission must remain read-only")
    _require(f"actions/checkout@{CHECKOUT_SHA}" in workflow, "checkout action must be SHA-pinned")
    _require(
        f"aws-actions/configure-aws-credentials@{AWS_CREDENTIALS_SHA}" in workflow,
        "AWS credential action must be SHA-pinned",
    )
    _require(
        f"hashicorp/setup-terraform@{SETUP_TERRAFORM_SHA}" in workflow,
        "Terraform setup action must be SHA-pinned",
    )
    for requirement in (
        "allowed-account-ids:",
        "unset-current-credentials: true",
        "validate_production_plan_inputs.py",
        "-detailed-exitcode",
        "-lock-timeout=5m",
        "summarize_terraform_plan.py",
        "--max-changes 50",
        "git diff --exit-code -- .terraform.lock.hcl",
        "if: always()",
    ):
        _require(requirement in workflow, f"missing workflow guard: {requirement}")
    _require("terraform apply" not in workflow.lower(), "production workflow must not apply")
    _require("upload-artifact" not in workflow.lower(), "sensitive plan files must not be artifacts")
    for forbidden in (
        "aws_access_key_id",
        "aws_secret_access_key",
        "access_key:",
        "secret_key:",
    ):
        _require(forbidden not in combined.lower(), f"static credential field found: {forbidden}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("workflow", type=Path)
    args = parser.parse_args()
    try:
        validate(args.root, args.workflow)
    except (OSError, ContractError) as exc:
        parser.error(str(exc))
    print("Production Terraform plan contract is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
