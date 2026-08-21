#!/usr/bin/env python3
"""Render a deployable Alertmanager config without copying webhook secrets."""

import argparse
import os
from pathlib import Path
import stat
import tempfile
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "infra" / "alertmanager" / "alertmanager.webhook.example.yml"
PLACEHOLDER_URL = "https://alerts.example.com/v1/thermoform"
TOKEN_FILENAME = "thermoform_alert_webhook_token"


def validate_webhook_url(value: str, allow_http: bool = False) -> str:
    if not value or any(character.isspace() for character in value):
        raise ValueError("webhook URL must not contain whitespace")
    if not value.isascii() or any(character in value for character in {'"', "'", "\\"}):
        raise ValueError("webhook URL must use an ASCII, YAML-safe representation")
    parsed = urlsplit(value)
    if parsed.username or parsed.password:
        raise ValueError("webhook URL must not contain credentials")
    if parsed.fragment:
        raise ValueError("webhook URL must not contain a fragment")
    if not parsed.hostname:
        raise ValueError("webhook URL must include a host")
    if parsed.scheme == "https":
        return value
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "receiver-fixture"}
    if parsed.scheme == "http" and allow_http and loopback:
        return value
    raise ValueError("webhook URL must use HTTPS")


def validate_token_file(secret_dir: Path) -> Path:
    token_file = secret_dir / TOKEN_FILENAME
    if not token_file.is_file():
        raise ValueError(f"missing token file: {token_file}")
    mode = stat.S_IMODE(token_file.stat().st_mode)
    if mode & 0o037:
        raise ValueError(f"token file must have mode 0640 or stricter: {token_file}")
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("token file must not be empty")
    if len(token.encode("utf-8")) > 4096:
        raise ValueError("token file exceeds 4096 bytes")
    return token_file


def render_config(webhook_url: str, secret_dir: Path, output: Path, allow_http=False):
    validated_url = validate_webhook_url(webhook_url, allow_http=allow_http)
    token_file = validate_token_file(secret_dir)
    if output.resolve() in {TEMPLATE.resolve(), token_file.resolve()}:
        raise ValueError("output must not overwrite the template or token file")
    source = TEMPLATE.read_text(encoding="utf-8")
    if source.count(PLACEHOLDER_URL) != 3:
        raise ValueError("Alertmanager template must contain three webhook URL markers")
    rendered = source.replace(PLACEHOLDER_URL, validated_url)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, delete=False
    ) as handle:
        handle.write(rendered)
        temporary = Path(handle.name)
    os.chmod(temporary, 0o644)
    os.replace(temporary, output)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--webhook-url", required=True)
    parser.add_argument("--secret-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-http",
        action="store_true",
        help="allow HTTP only for loopback or the isolated receiver fixture",
    )
    args = parser.parse_args()
    try:
        output = render_config(
            args.webhook_url,
            args.secret_dir.resolve(),
            args.output.resolve(),
            allow_http=args.allow_http,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(output)


if __name__ == "__main__":
    main()
