#!/usr/bin/env python3
"""Render a credential-free Thanos S3 config for workload-identity deployments."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
LOCAL_FILESYSTEM_CONFIG = ROOT / "infra" / "thanos" / "object-store.yml"
BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
REGION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")
PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}[A-Za-z0-9]$")
KMS_KEY_PATTERN = re.compile(r"^[A-Za-z0-9:/_-]{1,2048}$")
RESERVED_BUCKET_PREFIXES = ("xn--", "sthree-", "amzn-s3-demo-")
RESERVED_BUCKET_SUFFIXES = ("-s3alias", "--ol-s3", ".mrap", "--x-s3", "--table-s3")
BUCKET_LOOKUP_TYPES = ("auto", "virtual-hosted", "path")


def validate_bucket(value: str) -> str:
    if not BUCKET_PATTERN.fullmatch(value):
        raise ValueError("bucket must be a 3-63 character lowercase DNS-compatible name")
    if ".." in value or ".-" in value or "-." in value:
        raise ValueError("bucket contains an invalid adjacent separator")
    if value.startswith(RESERVED_BUCKET_PREFIXES) or value.endswith(
        RESERVED_BUCKET_SUFFIXES
    ):
        raise ValueError("bucket uses an AWS-reserved name")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise ValueError("bucket must not be formatted as an IP address")


def validate_endpoint(value: str) -> str:
    if not value or not value.isascii() or any(character.isspace() for character in value):
        raise ValueError("endpoint must be a nonempty ASCII host with no whitespace")
    if "://" in value or any(character in value for character in "/?#@\\\"'"):
        raise ValueError("endpoint must be host[:port] without scheme, path, or credentials")
    try:
        parsed = urlsplit(f"https://{value}")
        port = parsed.port
    except ValueError as error:
        raise ValueError("endpoint contains an invalid port or host") from error
    if not parsed.hostname or parsed.netloc != value:
        raise ValueError("endpoint must be host[:port] without scheme, path, or credentials")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("endpoint port must be between 1 and 65535")
    return value


def validate_region(value: str) -> str:
    if not REGION_PATTERN.fullmatch(value):
        raise ValueError("region must be a lowercase AWS-style region identifier")
    return value


def validate_prefix(value: str) -> str:
    if not PREFIX_PATTERN.fullmatch(value):
        raise ValueError("prefix must be 2-256 path-safe characters")
    if "//" in value or any(part in {".", ".."} for part in value.split("/")):
        raise ValueError("prefix must not contain empty, dot, or parent path segments")
    return value


def validate_kms_key_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not KMS_KEY_PATTERN.fullmatch(value):
        raise ValueError("KMS key ID must use an ARN, key ID, or alias-safe representation")
    return value


def quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def render_config(
    bucket: str,
    endpoint: str,
    region: str,
    prefix: str,
    output: Path,
    *,
    bucket_lookup_type: str = "auto",
    kms_key_id: str | None = None,
) -> Path:
    bucket = validate_bucket(bucket)
    endpoint = validate_endpoint(endpoint)
    region = validate_region(region)
    prefix = validate_prefix(prefix)
    kms_key_id = validate_kms_key_id(kms_key_id)
    if bucket_lookup_type not in BUCKET_LOOKUP_TYPES:
        raise ValueError("bucket lookup type must be auto, virtual-hosted, or path")
    output = output.resolve()
    if output == LOCAL_FILESYSTEM_CONFIG.resolve():
        raise ValueError("output must not overwrite the checked-in filesystem config")

    sse_type = "SSE-KMS" if kms_key_id else "SSE-S3"
    lines = [
        "type: S3",
        "config:",
        f"  bucket: {quoted(bucket)}",
        f"  endpoint: {quoted(endpoint)}",
        f"  region: {quoted(region)}",
        "  disable_dualstack: false",
        "  aws_sdk_auth: true",
        "  insecure: false",
        "  signature_version2: false",
        f"  bucket_lookup_type: {quoted(bucket_lookup_type)}",
        "  send_content_md5: true",
        "  sse_config:",
        f"    type: {quoted(sse_type)}",
    ]
    if kms_key_id:
        lines.append(f"    kms_key_id: {quoted(kms_key_id)}")
    lines.append(f"prefix: {quoted(prefix)}")
    rendered = "\n".join(lines) + "\n"
    forbidden = ("access_key:", "secret_key:", "session_token:")
    if any(marker in rendered for marker in forbidden):
        raise RuntimeError("renderer must never emit static credential fields")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, delete=False
    ) as handle:
        handle.write(rendered)
        temporary = Path(handle.name)
    os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    os.replace(temporary, output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--prefix", default="thermoform/metrics")
    parser.add_argument("--bucket-lookup-type", choices=BUCKET_LOOKUP_TYPES, default="auto")
    parser.add_argument("--sse-kms-key-id")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = render_config(
            args.bucket,
            args.endpoint,
            args.region,
            args.prefix,
            args.output,
            bucket_lookup_type=args.bucket_lookup_type,
            kms_key_id=args.sse_kms_key_id,
        )
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(output)


if __name__ == "__main__":
    main()
