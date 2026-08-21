#!/usr/bin/env python3
"""Exercise metrics fixture -> Prometheus -> Alertmanager with isolated Compose."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "infra" / "observability-drill" / "docker-compose.yml"
PROJECT_NAME = "thermoform-observability-drill"
PROMETHEUS_URL = "http://127.0.0.1:19090"
PROMETHEUS_2_URL = "http://127.0.0.1:19091"
ALERTMANAGER_URL = "http://127.0.0.1:19093"
ALERTMANAGER_2_URL = "http://127.0.0.1:19095"
RECEIVER_URL = "http://127.0.0.1:19094"
METRICS_FIXTURE_URL = "http://127.0.0.1:19096"
THANOS_QUERY_URL = "http://127.0.0.1:19097"
THANOS_RECEIVE_URL = "http://127.0.0.1:19098"
THANOS_RECEIVE_2_URL = "http://127.0.0.1:19110"
THANOS_RECEIVE_3_URL = "http://127.0.0.1:19111"
THANOS_STORE_URL = "http://127.0.0.1:19112"
THANOS_COMPACT_URL = "http://127.0.0.1:19113"
ALERT_NAME = "ThermoformCaeWatchdogMissingDrill"
RECEIVE_FAILOVER_ALERT_NAME = "ThermoformReceiveFailoverDrill"
PROMETHEUS_FAILOVER_ALERT_NAME = "ThermoformPrometheusFailoverDrill"
FAILOVER_ALERT_NAME = "ThermoformAlertmanagerFailoverDrill"
EXPECTED_GROUPS = {
    "thermoform-cae-resume",
    "thermoform-cae-slo-recording",
    "thermoform-cae-slo-alerts",
    "thermoform-alert-delivery",
    "thermoform-observability-storage",
    "thermoform-prometheus-ha",
    "thermoform-cae-observability-drill",
}


def compose(*args, check=True, capture_output=False, environment=None):
    return subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            PROJECT_NAME,
            "--file",
            str(COMPOSE_FILE),
            *args,
        ],
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=capture_output,
        env=environment,
    )


def get_json(url):
    with urlopen(url, timeout=3) as response:
        return json.load(response)


def wait_for(description, probe, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    last_error = None
    while time.monotonic() < deadline:
        try:
            result = probe()
            if result:
                return result
        except (OSError, URLError, ValueError, KeyError) as error:
            last_error = error
        time.sleep(1)
    detail = f"; last error: {last_error}" if last_error else ""
    raise RuntimeError(f"timed out waiting for {description}{detail}")


def prometheus_alert_probe(alert_name, url=PROMETHEUS_URL):
    payload = get_json(f"{url}/api/v1/rules")
    groups = payload["data"]["groups"]
    names = {group["name"] for group in groups}
    if not EXPECTED_GROUPS.issubset(names):
        return None
    for group in groups:
        for rule in group.get("rules", []):
            if rule.get("name") == alert_name and rule.get("state") == "firing":
                return names
    return None


def metrics_tier_probe():
    urls = (
        f"{PROMETHEUS_URL}/-/ready",
        f"{PROMETHEUS_2_URL}/-/ready",
        f"{THANOS_RECEIVE_URL}/-/ready",
        f"{THANOS_RECEIVE_2_URL}/-/ready",
        f"{THANOS_RECEIVE_3_URL}/-/ready",
        f"{THANOS_STORE_URL}/-/ready",
        f"{THANOS_COMPACT_URL}/-/ready",
        f"{THANOS_QUERY_URL}/-/ready",
    )
    for url in urls:
        with urlopen(url, timeout=3) as response:
            if response.status != 200:
                return None
    return urls


def remote_copy_probe(phase, expected_prometheus_replicas, expected_receive_replicas):
    parameters = urlencode(
        {
            "query": f"thermoform_observability_drill_phase == {phase}",
            "dedup": "false",
        }
    )
    payload = get_json(f"{THANOS_QUERY_URL}/api/v1/query?{parameters}")
    if payload.get("status") != "success":
        return None
    copies = {
        (
            result.get("metric", {}).get("replica"),
            result.get("metric", {}).get("receive_replica"),
        )
        for result in payload.get("data", {}).get("result", [])
    }
    expected = {
        (prometheus_replica, receive_replica)
        for prometheus_replica in expected_prometheus_replicas
        for receive_replica in expected_receive_replicas
    }
    return copies if copies == expected else None


def deduplicated_remote_probe(phase):
    parameters = urlencode(
        {"query": f"thermoform_observability_drill_phase == {phase}"}
    )
    payload = get_json(f"{THANOS_QUERY_URL}/api/v1/query?{parameters}")
    results = payload.get("data", {}).get("result", [])
    if payload.get("status") != "success" or len(results) != 1:
        return None
    return results[0] if "replica" not in results[0].get("metric", {}) else None


def cluster_probe():
    statuses = [
        get_json(f"{url}/api/v2/status") for url in (ALERTMANAGER_URL, ALERTMANAGER_2_URL)
    ]
    if all(
        status.get("cluster", {}).get("status") == "ready"
        and len(status.get("cluster", {}).get("peers", [])) == 2
        for status in statuses
    ):
        return statuses
    return None


def set_phase(phase):
    request = Request(f"{METRICS_FIXTURE_URL}/phase/{phase}", data=b"", method="POST")
    with urlopen(request, timeout=3) as response:
        if response.status != 204:
            raise RuntimeError(f"metrics fixture rejected phase {phase}")


def create_silence(comment):
    now = datetime.now(timezone.utc)
    payload = {
        "matchers": [
            {"name": "alertname", "value": "NeverFiresInHaDrill", "isRegex": False}
        ],
        "startsAt": (now - timedelta(minutes=1)).isoformat(),
        "endsAt": (now + timedelta(hours=1)).isoformat(),
        "createdBy": "thermoform-ha-drill",
        "comment": comment,
    }
    request = Request(
        f"{ALERTMANAGER_URL}/api/v2/silences",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return json.load(response)["silenceID"]


def replicated_silence_probe(silence_id, comment):
    for silence in get_json(f"{ALERTMANAGER_2_URL}/api/v2/silences"):
        if silence.get("id") == silence_id and silence.get("comment") == comment:
            return silence
    return None


def alertmanager_probe(alert_name, url=ALERTMANAGER_URL):
    groups = get_json(f"{url}/api/v2/alerts/groups")
    for group in groups:
        receiver = group.get("receiver", {}).get("name")
        for alert in group.get("alerts", []):
            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})
            if labels.get("alertname") != alert_name:
                continue
            if receiver != "warning-operations-webhook":
                raise RuntimeError(f"unexpected receiver: {receiver}")
            if labels.get("drill") != "true":
                raise RuntimeError("drill alert lost its safety label")
            if not annotations.get("runbook_url"):
                raise RuntimeError("drill alert has no production runbook link")
            return receiver
    return None


def receiver_probe(alert_name):
    deliveries = get_json(f"{RECEIVER_URL}/deliveries")["deliveries"]
    for delivery in deliveries:
        if alert_name not in delivery.get("alertnames", []):
            continue
        if delivery.get("receiver") != "warning-operations-webhook":
            raise RuntimeError(
                f"receiver fixture observed wrong route: {delivery.get('receiver')}"
            )
        if delivery.get("status") != "firing" or not delivery.get("groupKey"):
            raise RuntimeError("receiver fixture observed an invalid webhook payload")
        return delivery
    return None


def prepare_runtime_directory():
    runtime_dir = Path(tempfile.mkdtemp(prefix="thermoform-alert-drill-"))
    secret_dir = runtime_dir / "secrets"
    secret_dir.mkdir()
    runtime_dir.chmod(0o750)
    secret_dir.chmod(0o750)
    token = secret_dir / "thermoform_alert_webhook_token"
    token.write_text("drill-token-not-a-secret\n", encoding="utf-8")
    token.chmod(0o640)
    config = runtime_dir / "alertmanager.yml"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "render_alertmanager_runtime.py"),
            "--webhook-url",
            "http://receiver-fixture:8080/v1/thermoform",
            "--secret-dir",
            str(secret_dir),
            "--output",
            str(config),
            "--allow-http",
        ],
        cwd=ROOT,
        check=True,
    )
    environment = os.environ.copy()
    environment["THERMOFORM_DRILL_ALERTMANAGER_CONFIG"] = str(config)
    environment["THERMOFORM_DRILL_SECRET_DIR"] = str(secret_dir)
    environment["THERMOFORM_DRILL_SECRET_GID"] = str(os.getgid())
    return runtime_dir, environment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="keep drill containers")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    runtime_dir = None
    environment = None
    try:
        runtime_dir, environment = prepare_runtime_directory()
        compose(
            "up", "--detach", "--remove-orphans", environment=environment
        )
        cluster = wait_for(
            "both Alertmanager peers to form a ready cluster",
            cluster_probe,
            args.timeout,
        )
        wait_for(
            "both Prometheus replicas and the Thanos query path",
            metrics_tier_probe,
            args.timeout,
        )
        silence_comment = f"replicated-{PROJECT_NAME}"
        silence_id = create_silence(silence_comment)
        wait_for(
            "the primary silence to replicate to the second peer",
            lambda: replicated_silence_probe(silence_id, silence_comment),
            args.timeout,
        )
        set_phase(1)
        rule_groups = wait_for(
            "Prometheus to load production rules and fire the drill alert",
            lambda: prometheus_alert_probe(ALERT_NAME),
            args.timeout,
        )
        receiver = wait_for(
            "Alertmanager to receive and route the drill alert",
            lambda: alertmanager_probe(ALERT_NAME),
            args.timeout,
        )
        delivery = wait_for(
            "the authenticated external receiver to accept the alert",
            lambda: receiver_probe(ALERT_NAME),
            args.timeout,
        )
        initial_remote_copies = wait_for(
            "both Prometheus streams to replicate across all Receive ingesters",
            lambda: remote_copy_probe(
                1,
                {"prometheus-1", "prometheus-2"},
                {"receive-1", "receive-2", "receive-3"},
            ),
            args.timeout,
        )
        wait_for(
            "Thanos Query to expose one deduplicated logical drill series",
            lambda: deduplicated_remote_probe(1),
            args.timeout,
        )
        compose("stop", "--timeout", "20", "thanos-receive", environment=environment)
        set_phase(2)
        wait_for(
            "the Receive failover drill alert to fire",
            lambda: prometheus_alert_probe(RECEIVE_FAILOVER_ALERT_NAME),
            args.timeout,
        )
        receive_failover_delivery = wait_for(
            "the Receive failover alert to reach the authenticated receiver",
            lambda: receiver_probe(RECEIVE_FAILOVER_ALERT_NAME),
            args.timeout,
        )
        surviving_receive_copies = wait_for(
            "RF=3 writes to reach quorum through two surviving ingesters",
            lambda: remote_copy_probe(
                2,
                {"prometheus-1", "prometheus-2"},
                {"receive-2", "receive-3"},
            ),
            args.timeout,
        )
        wait_for(
            "Thanos Query to deduplicate the receiver-failover series",
            lambda: deduplicated_remote_probe(2),
            args.timeout,
        )
        compose("stop", "--timeout", "20", "prometheus", environment=environment)
        set_phase(3)
        wait_for(
            "the surviving Prometheus replica to fire a new alert",
            lambda: prometheus_alert_probe(
                PROMETHEUS_FAILOVER_ALERT_NAME, PROMETHEUS_2_URL
            ),
            args.timeout,
        )
        prometheus_failover_delivery = wait_for(
            "the Prometheus failover alert to reach the authenticated receiver",
            lambda: receiver_probe(PROMETHEUS_FAILOVER_ALERT_NAME),
            args.timeout,
        )
        surviving_remote_replicas = wait_for(
            "the surviving Prometheus replica to continue remote write",
            lambda: remote_copy_probe(
                3,
                {"prometheus-2"},
                {"receive-2", "receive-3"},
            ),
            args.timeout,
        )
        compose("stop", "--timeout", "20", "alertmanager", environment=environment)
        set_phase(4)
        wait_for(
            "Prometheus to fire a new alert after primary failure",
            lambda: prometheus_alert_probe(FAILOVER_ALERT_NAME, PROMETHEUS_2_URL),
            args.timeout,
        )
        failover_receiver = wait_for(
            "the surviving Alertmanager to accept the failover alert",
            lambda: alertmanager_probe(FAILOVER_ALERT_NAME, ALERTMANAGER_2_URL),
            args.timeout,
        )
        failover_delivery = wait_for(
            "the surviving Alertmanager to deliver the new alert",
            lambda: receiver_probe(FAILOVER_ALERT_NAME),
            args.timeout,
        )
        print(
            f"PASS: {ALERT_NAME} traversed metrics fixture -> Prometheus -> "
            f"Alertmanager receiver {receiver} -> authenticated webhook fixture; "
            f"initial group {delivery['groupKey']}; "
            f"{len(initial_remote_copies)} initial replicated copies; first Receive "
            f"stop retained {sorted(surviving_receive_copies)} via group "
            f"{receive_failover_delivery['groupKey']}; primary Prometheus "
            f"stop retained {sorted(surviving_remote_replicas)} via group "
            f"{prometheus_failover_delivery['groupKey']}; "
            f"{len(cluster)} peers replicated silence {silence_id}; primary stop "
            f"failed over {FAILOVER_ALERT_NAME} through {failover_receiver}, group "
            f"{failover_delivery['groupKey']}; {len(rule_groups)} rule groups loaded."
        )
        return 0
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        if environment is not None:
            compose("logs", "--no-color", check=False, environment=environment)
        return 1
    finally:
        if environment is not None and not args.keep:
            compose(
                "down",
                "--volumes",
                "--remove-orphans",
                check=False,
                environment=environment,
            )
        if runtime_dir is not None:
            if args.keep:
                print(f"Runtime config retained at {runtime_dir}")
            else:
                shutil.rmtree(runtime_dir)


if __name__ == "__main__":
    raise SystemExit(main())
