import json
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_prometheus_scrapes_fastapi_and_loads_cae_alerts():
    config = ROOT.joinpath("infra/prometheus/prometheus.yml").read_text(
        encoding="utf-8"
    )
    alerts = ROOT.joinpath("infra/prometheus/alerts.yml").read_text(
        encoding="utf-8"
    )

    assert "backend:8000" in config
    assert "metrics_path: /metrics" in config
    assert "/etc/prometheus/alerts.yml" in config
    assert "/etc/prometheus/slo.yml" in config
    assert "alertmanager:9093" in config
    assert "ThermoformCaeWatchdogMissing" in alerts
    assert "ThermoformCaeWatchdogStale" in alerts
    assert "ThermoformCaeResumeHeartbeatStale" in alerts
    assert "ThermoformCaeOrphanRepairDetected" in alerts
    assert "ThermoformCaeRetryFailed" in alerts
    assert alerts.count("runbook_url:") == 6
    assert alerts.count("team: thermal-platform") == 6


def test_grafana_dashboard_and_shared_watchdog_artifacts_are_provisioned():
    dashboard = json.loads(
        ROOT.joinpath(
            "infra/grafana/dashboards/cae-resume-observability.json"
        ).read_text(encoding="utf-8")
    )
    compose = ROOT.joinpath("docker-compose.yml").read_text(encoding="utf-8")

    assert dashboard["uid"] == "thermoform-cae-resume"
    assert len(dashboard["panels"]) == 9
    expressions = {
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    }
    assert "thermoform_cae:slo_recovery_availability:ratio_30d" in expressions
    assert (
        "thermoform_cae:slo_recovery_error_budget:remaining_ratio_30d"
        in expressions
    )
    assert "prometheus:" in compose
    assert "alertmanager:" in compose
    assert "grafana:" in compose
    watchdog = compose.split("  watchdog:", 1)[1].split("\n  prometheus:", 1)[0]
    assert "thermoform-artifacts:/data" in watchdog


def test_alertmanager_groups_routes_and_inhibits_recovery_alerts():
    config = ROOT.joinpath(
        "infra/alertmanager/alertmanager.yml"
    ).read_text(encoding="utf-8")
    example = ROOT.joinpath(
        "infra/alertmanager/alertmanager.webhook.example.yml"
    ).read_text(encoding="utf-8")
    runbook = ROOT.joinpath(
        "docs/runbooks/cae-observability.md"
    ).read_text(encoding="utf-8")

    assert "group_by:" in config
    assert 'severity="critical"' in config
    assert 'severity="warning"' in config
    assert 'alertname="ThermoformCaeApiDown"' in config
    assert 'alertname="ThermoformCaeWatchdogMissing"' in config
    assert "credentials_file:" in example
    assert "credentials:" not in example
    for alert in (
        "ThermoformCaeApiDown",
        "ThermoformCaeWatchdogMissing",
        "ThermoformCaeWatchdogStale",
        "ThermoformCaeResumeHeartbeatStale",
        "ThermoformCaeOrphanRepairDetected",
        "ThermoformCaeRetryFailed",
        "ThermoformCaeRecoverySloFastBurn",
        "ThermoformCaeRecoverySloSlowBurn",
        "ThermoformCaeRecoverySliMissing",
    ):
        assert f"## {alert}" in runbook


def test_recovery_slo_has_recording_rules_burn_alerts_and_promtool_tests():
    rules = ROOT.joinpath("infra/prometheus/slo.yml").read_text(encoding="utf-8")
    tests = ROOT.joinpath("infra/prometheus/tests/slo.test.yml").read_text(
        encoding="utf-8"
    )

    assert "thermoform_cae:sli_recovery_available" in rules
    assert "ratio_30d" in rules
    assert "remaining_ratio_30d" in rules
    assert rules.count("objective: \"99.5\"") == 3
    assert "ThermoformCaeRecoverySloFastBurn" in rules
    assert "ThermoformCaeRecoverySloSlowBurn" in rules
    assert "ThermoformCaeRecoverySliMissing" in rules
    assert "healthy recovery preserves the complete error budget" in tests
    assert "sustained recovery failure triggers multi-window burn alerts" in tests


def test_observability_drill_is_isolated_and_checks_the_warning_route():
    compose = ROOT.joinpath(
        "infra/observability-drill/docker-compose.yml"
    ).read_text(encoding="utf-8")
    rule = ROOT.joinpath(
        "infra/observability-drill/watchdog-missing.yml"
    ).read_text(encoding="utf-8")
    script = ROOT.joinpath(
        "scripts/run_observability_alert_drill.py"
    ).read_text(encoding="utf-8")

    assert "metrics-fixture:" in compose
    assert "127.0.0.1:19090:9090" in compose
    assert "127.0.0.1:19093:9093" in compose
    assert "ThermoformCaeWatchdogMissingDrill" in rule
    assert 'drill: "true"' in rule
    assert 'PROJECT_NAME = "thermoform-observability-drill"' in script
    assert 'receiver != "warning-operations"' in script
    assert '"down", "--volumes", "--remove-orphans"' in script


def test_ci_validates_every_observability_configuration():
    workflow = ROOT.joinpath(
        ".github/workflows/observability-config.yml"
    ).read_text(encoding="utf-8")

    assert "docker compose config --quiet" in workflow
    assert "promtool" in workflow
    assert "check config /etc/prometheus/prometheus.yml" in workflow
    assert "test rules /etc/prometheus/tests/slo.test.yml" in workflow
    assert "amtool" in workflow
    assert "check-config /etc/alertmanager/alertmanager.yml" in workflow
    assert "python -m json.tool" in workflow
    assert "python scripts/run_observability_alert_drill.py" in workflow
