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
    assert "ThermoformCaeWatchdogMissing" in alerts
    assert "ThermoformCaeWatchdogStale" in alerts
    assert "ThermoformCaeResumeHeartbeatStale" in alerts
    assert "ThermoformCaeOrphanRepairDetected" in alerts
    assert "ThermoformCaeRetryFailed" in alerts


def test_grafana_dashboard_and_shared_watchdog_artifacts_are_provisioned():
    dashboard = json.loads(
        ROOT.joinpath(
            "infra/grafana/dashboards/cae-resume-observability.json"
        ).read_text(encoding="utf-8")
    )
    compose = ROOT.joinpath("docker-compose.yml").read_text(encoding="utf-8")

    assert dashboard["uid"] == "thermoform-cae-resume"
    assert len(dashboard["panels"]) == 6
    assert "prometheus:" in compose
    assert "grafana:" in compose
    watchdog = compose.split("  watchdog:", 1)[1].split("\n  prometheus:", 1)[0]
    assert "thermoform-artifacts:/data" in watchdog
