from pathlib import Path
import runpy

import pytest


ROOT = Path(__file__).parents[2]
RUNTIME = runpy.run_path(str(ROOT / "scripts" / "render_alertmanager_runtime.py"))
render_config = RUNTIME["render_config"]
validate_webhook_url = RUNTIME["validate_webhook_url"]


def make_secret_dir(tmp_path: Path, mode: int = 0o640) -> Path:
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir(parents=True)
    token = secret_dir / "thermoform_alert_webhook_token"
    token.write_text("runtime-token-not-embedded\n", encoding="utf-8")
    token.chmod(mode)
    return secret_dir


def test_runtime_renderer_replaces_all_routes_without_copying_token(tmp_path):
    secret_dir = make_secret_dir(tmp_path)
    output = tmp_path / "runtime" / "alertmanager.yml"

    render_config(
        "https://incident.example.net/hooks/thermoform",
        secret_dir,
        output,
    )

    rendered = output.read_text(encoding="utf-8")
    assert rendered.count("https://incident.example.net/hooks/thermoform") == 3
    assert "alerts.example.com" not in rendered
    assert "runtime-token-not-embedded" not in rendered
    assert rendered.count("credentials_file:") == 3
    assert output.stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize(
    "url",
    (
        "http://incident.example.net/hooks",
        "https://user:password@incident.example.net/hooks",
        "https://incident.example.net/hooks#fragment",
        "https://incident.example.net/hook\nreceiver: injected",
        'https://incident.example.net/"injected',
        "file:///tmp/receiver",
    ),
)
def test_runtime_renderer_rejects_unsafe_webhook_urls(url):
    with pytest.raises(ValueError):
        validate_webhook_url(url)


def test_runtime_renderer_allows_http_only_for_explicit_drill_fixture():
    assert (
        validate_webhook_url(
            "http://receiver-fixture:8080/v1/thermoform", allow_http=True
        )
        == "http://receiver-fixture:8080/v1/thermoform"
    )
    with pytest.raises(ValueError):
        validate_webhook_url("http://external.example.net/hook", allow_http=True)


def test_runtime_renderer_rejects_permissive_or_empty_token_files(tmp_path):
    permissive = make_secret_dir(tmp_path / "permissive", mode=0o664)
    with pytest.raises(ValueError, match="mode 0640"):
        render_config("https://incident.example.net/hook", permissive, tmp_path / "a.yml")

    empty_root = tmp_path / "empty"
    empty = make_secret_dir(empty_root)
    (empty / "thermoform_alert_webhook_token").write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must not be empty"):
        render_config("https://incident.example.net/hook", empty, tmp_path / "b.yml")


def test_runtime_renderer_cannot_overwrite_template_or_token(tmp_path):
    secret_dir = make_secret_dir(tmp_path)
    token = secret_dir / "thermoform_alert_webhook_token"
    with pytest.raises(ValueError, match="must not overwrite"):
        render_config("https://incident.example.net/hook", secret_dir, token)
    with pytest.raises(ValueError, match="must not overwrite"):
        render_config("https://incident.example.net/hook", secret_dir, RUNTIME["TEMPLATE"])
