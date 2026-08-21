#!/usr/bin/env python3
"""Exercise metrics fixture -> Prometheus -> Alertmanager with isolated Compose."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "infra" / "observability-drill" / "docker-compose.yml"
PROJECT_NAME = "thermoform-observability-drill"
PROMETHEUS_URL = "http://127.0.0.1:19090"
ALERTMANAGER_URL = "http://127.0.0.1:19093"
ALERT_NAME = "ThermoformCaeWatchdogMissingDrill"
EXPECTED_GROUPS = {
    "thermoform-cae-resume",
    "thermoform-cae-slo-recording",
    "thermoform-cae-slo-alerts",
    "thermoform-cae-observability-drill",
}


def compose(*args, check=True, capture_output=False):
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


def prometheus_probe():
    payload = get_json(f"{PROMETHEUS_URL}/api/v1/rules")
    groups = payload["data"]["groups"]
    names = {group["name"] for group in groups}
    if not EXPECTED_GROUPS.issubset(names):
        return None
    for group in groups:
        for rule in group.get("rules", []):
            if rule.get("name") == ALERT_NAME and rule.get("state") == "firing":
                return names
    return None


def alertmanager_probe():
    groups = get_json(f"{ALERTMANAGER_URL}/api/v2/alerts/groups")
    for group in groups:
        receiver = group.get("receiver", {}).get("name")
        for alert in group.get("alerts", []):
            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})
            if labels.get("alertname") != ALERT_NAME:
                continue
            if receiver != "warning-operations":
                raise RuntimeError(f"unexpected receiver: {receiver}")
            if labels.get("drill") != "true":
                raise RuntimeError("drill alert lost its safety label")
            if "cae-observability.md#thermoformcaewatchdogmissing" not in annotations.get(
                "runbook_url", ""
            ):
                raise RuntimeError("drill alert has no production runbook link")
            return receiver
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="keep drill containers")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    try:
        compose("up", "--detach", "--remove-orphans")
        rule_groups = wait_for(
            "Prometheus to load production rules and fire the drill alert",
            prometheus_probe,
            args.timeout,
        )
        receiver = wait_for(
            "Alertmanager to receive and route the drill alert",
            alertmanager_probe,
            args.timeout,
        )
        print(
            f"PASS: {ALERT_NAME} traversed metrics fixture -> Prometheus -> "
            f"Alertmanager receiver {receiver}; {len(rule_groups)} rule groups loaded."
        )
        return 0
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        compose("logs", "--no-color", check=False)
        return 1
    finally:
        if not args.keep:
            compose("down", "--volumes", "--remove-orphans", check=False)


if __name__ == "__main__":
    raise SystemExit(main())
