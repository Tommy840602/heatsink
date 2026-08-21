from pathlib import Path
import runpy
import shutil
import subprocess

import pytest


ROOT = Path(__file__).parents[2]
RUNTIME = runpy.run_path(str(ROOT / "scripts" / "render_eks_thanos_manifest.py"))
render_manifest = RUNTIME["render_manifest"]
validate_role_arn = RUNTIME["validate_role_arn"]
pytestmark = pytest.mark.skipif(
    shutil.which("kubectl") is None,
    reason="kubectl is required to render the EKS Kustomize template",
)


def _template(tmp_path: Path) -> Path:
    output = tmp_path / "eks-template.yml"
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "infra/kubernetes/overlays/aws-eks")],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    output.write_text(rendered, encoding="utf-8")
    return output


def test_renderer_binds_distinct_irsa_roles_without_static_credentials(tmp_path):
    output = tmp_path / "runtime" / "eks.yml"
    render_manifest(
        _template(tmp_path),
        output,
        receive_role_arn="arn:aws:iam::123456789012:role/thermoform-receive",
        store_role_arn="arn:aws:iam::123456789012:role/thermoform-store",
        compact_role_arn="arn:aws:iam::123456789012:role/thermoform-compact",
    )

    rendered = output.read_text(encoding="utf-8")
    assert rendered.count("eks.amazonaws.com/role-arn:") == 3
    assert rendered.count('eks.amazonaws.com/sts-regional-endpoints: "true"') == 3
    assert "REPLACE_WITH_" not in rendered
    assert "000000000000" not in rendered
    assert "access_key:" not in rendered
    assert "secret_key:" not in rendered
    assert output.stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize(
    "role",
    (
        "arn:aws:iam::123:role/too-short-account",
        "arn:aws:iam::123456789012:user/not-a-role",
        "arn:aws:iam::123456789012:role/*",
        "arn:aws:iam::123456789012:role/",
        "not-an-arn",
    ),
)
def test_renderer_rejects_invalid_or_wildcard_role_arns(role):
    with pytest.raises(ValueError):
        validate_role_arn(role)


def test_renderer_rejects_shared_roles(tmp_path):
    role = "arn:aws:iam::123456789012:role/shared"

    with pytest.raises(ValueError, match="distinct"):
        render_manifest(
            _template(tmp_path),
            tmp_path / "eks.yml",
            receive_role_arn=role,
            store_role_arn=role,
            compact_role_arn="arn:aws:iam::123456789012:role/compact",
        )


def test_renderer_does_not_overwrite_template(tmp_path):
    template = _template(tmp_path)

    with pytest.raises(ValueError, match="must not overwrite"):
        render_manifest(
            template,
            template,
            receive_role_arn="arn:aws:iam::123456789012:role/receive",
            store_role_arn="arn:aws:iam::123456789012:role/store",
            compact_role_arn="arn:aws:iam::123456789012:role/compact",
        )
