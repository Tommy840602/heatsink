#!/usr/bin/env python3
"""Bind an EKS Thanos Kustomize template to reviewed IRSA roles."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import stat
import tempfile


ROLE_PATTERN = re.compile(
    r"^arn:(aws|aws-us-gov|aws-cn):iam::[0-9]{12}:role/"
    r"[A-Za-z0-9+=,.@_/-]{1,512}$"
)
ROLE_TOKENS = {
    "receive": "arn:aws:iam::000000000000:role/REPLACE_WITH_THANOS_RECEIVE_ROLE",
    "store": "arn:aws:iam::000000000000:role/REPLACE_WITH_THANOS_STORE_ROLE",
    "compact": "arn:aws:iam::000000000000:role/REPLACE_WITH_THANOS_COMPACT_ROLE",
}
FORBIDDEN_CREDENTIALS = (
    "access_key:",
    "secret_key:",
    "session_token:",
    "aws_access_key_id",
    "aws_secret_access_key",
)


def validate_role_arn(value: str) -> str:
    if not ROLE_PATTERN.fullmatch(value):
        raise ValueError("role ARN must be a complete AWS IAM role ARN")
    if "*" in value or value.endswith("/"):
        raise ValueError("role ARN must identify exactly one role")
    return value


def render_manifest(
    template: Path,
    output: Path,
    *,
    receive_role_arn: str,
    store_role_arn: str,
    compact_role_arn: str,
) -> Path:
    roles = {
        "receive": validate_role_arn(receive_role_arn),
        "store": validate_role_arn(store_role_arn),
        "compact": validate_role_arn(compact_role_arn),
    }
    if len(set(roles.values())) != 3:
        raise ValueError("Receive, Store, and Compactor must use distinct IAM roles")
    partitions = {role.split(":", 2)[1] for role in roles.values()}
    if len(partitions) != 1:
        raise ValueError("all IRSA roles must use the same AWS partition")

    template = template.resolve()
    output = output.resolve()
    if template == output:
        raise ValueError("output must not overwrite the rendered Kustomize template")
    rendered = template.read_text(encoding="utf-8")
    for component, token in ROLE_TOKENS.items():
        if rendered.count(token) != 1:
            raise ValueError(f"template must contain exactly one {component} role token")
        rendered = rendered.replace(token, roles[component])

    lowered = rendered.lower()
    if any(token.lower() in lowered for token in ROLE_TOKENS.values()):
        raise RuntimeError("rendered manifest still contains an IRSA placeholder")
    if any(marker in lowered for marker in FORBIDDEN_CREDENTIALS):
        raise RuntimeError("rendered manifest must not contain static AWS credentials")
    if "eks.amazonaws.com/role-arn:" not in rendered:
        raise RuntimeError("rendered manifest does not contain IRSA annotations")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, delete=False
    ) as handle:
        handle.write(rendered)
        temporary = Path(handle.name)
    os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    os.replace(temporary, output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--receive-role-arn", required=True)
    parser.add_argument("--store-role-arn", required=True)
    parser.add_argument("--compact-role-arn", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = render_manifest(
            args.template,
            args.output,
            receive_role_arn=args.receive_role_arn,
            store_role_arn=args.store_role_arn,
            compact_role_arn=args.compact_role_arn,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"Rendered credential-free EKS manifest: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
