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
    assert "/etc/prometheus/delivery.yml" in config
    assert "/etc/prometheus/storage.yml" in config
    assert "alertmanager:9093" in config
    assert "alertmanager-2:9093" in config
    assert "external_labels:" in config
    assert "replica: prometheus-1" in config
    assert "action: labeldrop" in config
    assert "job_name: thermoform-prometheus" in config
    assert "job_name: thermoform-alertmanager" in config
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
    assert len(dashboard["panels"]) == 14
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
    assert 'up{job="thermoform-alertmanager"}' in expressions
    assert any("alertmanager_notifications_failed_total" in item for item in expressions)
    assert "thermoform_observability:prometheus_storage_usage:ratio" in expressions
    assert any("silences_maintenance_errors_total" in item for item in expressions)
    assert any("alertmanager_cluster_members" in item for item in expressions)
    assert "prometheus:" in compose
    assert "alertmanager:" in compose
    assert "alertmanager-2:" in compose
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
    assert example.count("credentials_file:") == 3
    assert "local-delivery-fallback" in example
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
        "ThermoformAlertmanagerDown",
        "ThermoformAlertmanagerClusterDegraded",
        "ThermoformAlertmanagerClusterMembershipMismatch",
        "ThermoformAlertDeliveryFailure",
        "ThermoformPrometheusStorageBudgetHigh",
        "ThermoformPrometheusRetentionNotConfigured",
        "ThermoformAlertmanagerPersistenceFailure",
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


def test_alert_delivery_rules_use_native_alertmanager_metrics():
    rules = ROOT.joinpath("infra/prometheus/delivery.yml").read_text(
        encoding="utf-8"
    )
    tests = ROOT.joinpath(
        "infra/prometheus/tests/delivery.test.yml"
    ).read_text(encoding="utf-8")
    compose = ROOT.joinpath("docker-compose.yml").read_text(encoding="utf-8")

    assert "ThermoformAlertmanagerDown" in rules
    assert "ThermoformAlertmanagerClusterDegraded" in rules
    assert "ThermoformAlertmanagerClusterMembershipMismatch" in rules
    assert "ThermoformAlertDeliveryFailure" in rules
    assert "alertmanager_notifications_failed_total" in rules
    assert 'component: alert-delivery' in rules
    assert "alertmanager outage is visible independently of the api" in tests
    assert "one reachable replica reports degraded delivery redundancy" in tests
    assert "reachable replicas detect broken gossip membership" in tests
    assert "webhook counter increase triggers delivery failure" in tests
    assert "THERMOFORM_ALERTMANAGER_CONFIG" in compose
    assert "THERMOFORM_ALERT_SECRET_DIR" in compose
    assert "THERMOFORM_ALERT_SECRET_GID" in compose
    assert "--cluster.peer=alertmanager-2:9094" in compose
    assert "--cluster.peer=alertmanager:9094" in compose
    assert "alertmanager-2-data:/alertmanager" in compose


def test_observability_storage_retention_and_alerts_are_configured():
    rules = ROOT.joinpath("infra/prometheus/storage.yml").read_text(
        encoding="utf-8"
    )
    tests = ROOT.joinpath(
        "infra/prometheus/tests/storage.test.yml"
    ).read_text(encoding="utf-8")
    compose = ROOT.joinpath("docker-compose.yml").read_text(encoding="utf-8")

    assert "--storage.tsdb.retention.time=30d" in compose
    assert "--storage.tsdb.retention.size=8GB" in compose
    assert "prometheus_tsdb_retention_limit_bytes" in rules
    assert "ThermoformPrometheusStorageBudgetHigh" in rules
    assert "ThermoformPrometheusRetentionNotConfigured" in rules
    assert "ThermoformAlertmanagerPersistenceFailure" in rules
    assert "storage budget combines blocks wal and head chunks" in tests
    assert "--data.retention=${THERMOFORM_ALERTMANAGER_RETENTION:-120h}" in compose


def test_state_backup_tool_is_offline_scoped_and_restore_is_guarded():
    tool = ROOT.joinpath("scripts/observability_state.py").read_text(
        encoding="utf-8"
    )
    drill = ROOT.joinpath(
        "scripts/run_observability_state_drill.py"
    ).read_text(encoding="utf-8")
    compose = ROOT.joinpath(
        "infra/observability-state-drill/docker-compose.yml"
    ).read_text(encoding="utf-8")

    assert 'LEGACY_VOLUME_KEYS = ("prometheus-data", "alertmanager-data")' in tool
    assert 'VOLUME_KEYS = (*LEGACY_VOLUME_KEYS, "alertmanager-2-data")' in tool
    assert '"schema_version": 2' in tool
    assert "com.docker.compose.project" in tool
    assert "com.docker.compose.volume" in tool
    assert "--confirm-empty-volumes" in tool
    assert "is mounted by a running container" in tool
    assert "is not empty; refusing to overwrite state" in tool
    assert "validate_archive" in tool
    assert "StateRestoreDrill" in drill
    assert "ALERTMANAGER_2_URL" in drill
    assert '"down", "--volumes", "--remove-orphans"' in drill
    assert "prometheus-data:" in compose
    assert "alertmanager-data:" in compose
    assert "alertmanager-2-data:" in compose


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
    assert "127.0.0.1:19095:9093" in compose
    assert "ThermoformCaeWatchdogMissingDrill" in rule
    assert "ThermoformAlertmanagerFailoverDrill" in rule
    assert 'drill: "true"' in rule
    assert 'PROJECT_NAME = "thermoform-observability-drill"' in script
    assert "receiver-fixture:" in compose
    assert "127.0.0.1:19094:8080" in compose
    assert 'receiver != "warning-operations-webhook"' in script
    assert "render_alertmanager_runtime.py" in script
    assert "replicated_silence_probe" in script
    assert '"alertmanager", environment=environment' in script
    assert '"down",' in script
    assert '"--volumes",' in script
    assert '"--remove-orphans",' in script


def test_ci_validates_every_observability_configuration():
    workflow = ROOT.joinpath(
        ".github/workflows/observability-config.yml"
    ).read_text(encoding="utf-8")

    assert "docker compose config --quiet" in workflow
    assert "promtool" in workflow
    assert "check config /etc/prometheus/prometheus.yml" in workflow
    assert "test rules /etc/prometheus/tests/slo.test.yml" in workflow
    assert "test rules /etc/prometheus/tests/delivery.test.yml" in workflow
    assert "test rules /etc/prometheus/tests/storage.test.yml" in workflow
    assert "amtool" in workflow
    assert "check-config /etc/alertmanager/alertmanager.yml" in workflow
    assert "python -m json.tool" in workflow
    assert "python scripts/run_observability_alert_drill.py" in workflow
    assert "python scripts/render_alertmanager_runtime.py" in workflow
    assert "python scripts/run_observability_state_drill.py" in workflow
