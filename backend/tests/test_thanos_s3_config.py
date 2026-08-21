from pathlib import Path
import runpy

import pytest


ROOT = Path(__file__).parents[2]
RUNTIME = runpy.run_path(str(ROOT / "scripts" / "render_thanos_s3_config.py"))
render_config = RUNTIME["render_config"]
validate_bucket = RUNTIME["validate_bucket"]
validate_endpoint = RUNTIME["validate_endpoint"]
validate_prefix = RUNTIME["validate_prefix"]


def test_renderer_emits_workload_identity_s3_without_static_credentials(tmp_path):
    output = tmp_path / "runtime" / "object-store.yml"

    render_config(
        "thermoform-metrics-prod",
        "s3.ap-northeast-1.amazonaws.com",
        "ap-northeast-1",
        "thermoform/metrics",
        output,
    )

    rendered = output.read_text(encoding="utf-8")
    assert "type: S3" in rendered
    assert 'bucket: "thermoform-metrics-prod"' in rendered
    assert 'endpoint: "s3.ap-northeast-1.amazonaws.com"' in rendered
    assert 'region: "ap-northeast-1"' in rendered
    assert "aws_sdk_auth: true" in rendered
    assert "insecure: false" in rendered
    assert "signature_version2: false" in rendered
    assert 'type: "SSE-S3"' in rendered
    assert 'prefix: "thermoform/metrics"' in rendered
    assert all(
        marker not in rendered
        for marker in ("access_key:", "secret_key:", "session_token:")
    )
    assert output.stat().st_mode & 0o777 == 0o644


def test_renderer_supports_kms_and_path_style_without_embedding_keys(tmp_path):
    output = tmp_path / "object-store.yml"
    key = "arn:aws:kms:ap-northeast-1:123456789012:key/abc-123"

    render_config(
        "thermoform-metrics-prod",
        "object.example.net:9443",
        "ap-northeast-1",
        "thermoform/metrics",
        output,
        bucket_lookup_type="path",
        kms_key_id=key,
    )

    rendered = output.read_text(encoding="utf-8")
    assert 'bucket_lookup_type: "path"' in rendered
    assert 'type: "SSE-KMS"' in rendered
    assert f'kms_key_id: "{key}"' in rendered
    assert "secret_key:" not in rendered


@pytest.mark.parametrize(
    "bucket",
    (
        "ABCD",
        "ab",
        "192.168.0.1",
        "bad..bucket",
        "xn--reserved-name",
        "bucket-s3alias",
        "bad_bucket",
    ),
)
def test_renderer_rejects_nonportable_or_reserved_bucket_names(bucket):
    with pytest.raises(ValueError):
        validate_bucket(bucket)


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://s3.ap-northeast-1.amazonaws.com",
        "user@s3.example.net",
        "s3.example.net/path",
        "s3.example.net:70000",
        "s3.example.net\nconfig: injected",
    ),
)
def test_renderer_rejects_unsafe_endpoints(endpoint):
    with pytest.raises(ValueError):
        validate_endpoint(endpoint)


@pytest.mark.parametrize(
    "prefix",
    ("/absolute", "trailing/", "thermoform//metrics", "thermoform/../metrics"),
)
def test_renderer_rejects_unsafe_prefixes(prefix):
    with pytest.raises(ValueError):
        validate_prefix(prefix)


def test_renderer_cannot_replace_checked_in_filesystem_config():
    with pytest.raises(ValueError, match="must not overwrite"):
        render_config(
            "thermoform-metrics-prod",
            "s3.ap-northeast-1.amazonaws.com",
            "ap-northeast-1",
            "thermoform/metrics",
            RUNTIME["LOCAL_FILESYSTEM_CONFIG"],
        )
