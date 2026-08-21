#!/usr/bin/env python3
"""Prove offline observability backup/restore with real Alertmanager state."""

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
COMPOSE_FILE = (
    ROOT / "infra" / "observability-state-drill" / "docker-compose.yml"
)
PROJECT_NAME = f"thermoform-observability-state-drill-{os.getpid()}"
PROMETHEUS_URL = "http://127.0.0.1:19100"
PROMETHEUS_2_URL = "http://127.0.0.1:19104"
ALERTMANAGER_URL = "http://127.0.0.1:19101"
ALERTMANAGER_2_URL = "http://127.0.0.1:19102"
THANOS_QUERY_URL = "http://127.0.0.1:19103"
THANOS_RECEIVE_URL = "http://127.0.0.1:19105"
THANOS_RECEIVE_2_URL = "http://127.0.0.1:19113"
THANOS_RECEIVE_3_URL = "http://127.0.0.1:19114"
THANOS_STORE_URL = "http://127.0.0.1:19115"


def compose(*args, check=True):
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
    )


def state_tool(*args, check=True, capture_output=False):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "observability_state.py"), *args],
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=capture_output,
    )


def docker(*args, capture_output=False, check=True):
    return subprocess.run(
        ["docker", *args],
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=capture_output,
    )


def resolve_volume(volume_key):
    result = docker(
        "volume",
        "ls",
        "--filter",
        f"label=com.docker.compose.project={PROJECT_NAME}",
        "--filter",
        f"label=com.docker.compose.volume={volume_key}",
        "--format",
        "{{.Name}}",
        capture_output=True,
    )
    names = [line for line in result.stdout.splitlines() if line]
    if len(names) != 1:
        raise RuntimeError(f"expected one {volume_key} volume, found {len(names)}")
    return names[0]


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


def ready_probe():
    prometheus_ready = all(
        urlopen(f"{url}/-/ready", timeout=3).status == 200
        for url in (PROMETHEUS_URL, PROMETHEUS_2_URL)
    )
    with urlopen(f"{ALERTMANAGER_URL}/-/ready", timeout=3) as response:
        alertmanager_ready = response.status == 200
    with urlopen(f"{ALERTMANAGER_2_URL}/-/ready", timeout=3) as response:
        alertmanager_2_ready = response.status == 200
    thanos_ready = all(
        urlopen(f"{url}/-/ready", timeout=3).status == 200
        for url in (
            THANOS_QUERY_URL,
            THANOS_RECEIVE_URL,
            THANOS_RECEIVE_2_URL,
            THANOS_RECEIVE_3_URL,
            THANOS_STORE_URL,
        )
    )
    return prometheus_ready and alertmanager_ready and alertmanager_2_ready and thanos_ready


def remote_series_probe(query_time=None):
    suffix = "?query=up%7Bjob%3D%22thermoform-prometheus%22%7D&dedup=false"
    if query_time is not None:
        suffix += f"&time={query_time}"
    payload = get_json(f"{THANOS_QUERY_URL}/api/v1/query{suffix}")
    if payload.get("status") != "success":
        return None
    replicas = {
        item.get("metric", {}).get("replica")
        for item in payload.get("data", {}).get("result", [])
    }
    return sorted(replicas) if replicas == {"prometheus-1", "prometheus-2"} else None


def upload_object_store_fixture(fixture_dir):
    fixture_timestamp = int(time.time()) - 300
    fixture_dir.chmod(0o777)
    blocks_dir = fixture_dir / "blocks"
    blocks_dir.mkdir(mode=0o777)
    fixture_dir.joinpath("fixture.prom").write_text(
        "# HELP thermoform_object_store_drill Durable object-store drill sample.\n"
        "# TYPE thermoform_object_store_drill gauge\n"
        f"thermoform_object_store_drill{{source=\"fixture\"}} 1 {fixture_timestamp}\n"
        "# EOF\n",
        encoding="utf-8",
    )
    docker(
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--entrypoint",
        "promtool",
        "--volume",
        f"{fixture_dir}:/work",
        "prom/prometheus:v3.5.5",
        "tsdb",
        "create-blocks-from",
        "openmetrics",
        "/work/fixture.prom",
        "/work/blocks",
    )
    try:
        docker(
            "run",
            "--rm",
            "--user",
            "0:0",
            "--volume",
            f"{blocks_dir}:/blocks",
            "--volume",
            f"{resolve_volume('thanos-object-store-data')}:/thanos/object-store",
            "--volume",
            f"{ROOT / 'infra' / 'thanos' / 'object-store.yml'}:/etc/thanos/object-store.yml:ro",
            "quay.io/thanos/thanos:v0.42.4",
            "tools",
            "bucket",
            "--objstore.config-file=/etc/thanos/object-store.yml",
            "upload-blocks",
            "--path=/blocks",
            '--label=cluster="thermoform-state-drill"',
            '--label=replica="object-store-fixture"',
        )
    finally:
        docker(
            "run",
            "--rm",
            "--user",
            "0:0",
            "--volume",
            f"{fixture_dir}:/fixture",
            "alpine:3.22",
            "chown",
            "-R",
            f"{os.getuid()}:{os.getgid()}",
            "/fixture",
            check=False,
        )
    return fixture_timestamp


def object_store_fixture_probe(query_time):
    parameters = urlencode(
        {"query": "thermoform_object_store_drill", "time": query_time}
    )
    payload = get_json(f"{THANOS_QUERY_URL}/api/v1/query?{parameters}")
    results = payload.get("data", {}).get("result", [])
    for result in results:
        if result.get("metric", {}).get("source") == "fixture":
            return result
    return None


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


def create_silence(comment):
    now = datetime.now(timezone.utc)
    payload = {
        "matchers": [
            {"name": "alertname", "value": "StateRestoreDrill", "isRegex": False}
        ],
        "startsAt": (now - timedelta(minutes=1)).isoformat(),
        "endsAt": (now + timedelta(hours=1)).isoformat(),
        "createdBy": "thermoform-state-drill",
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


def restored_silence_probe(silence_id, comment, url=ALERTMANAGER_URL):
    silences = get_json(f"{url}/api/v2/silences")
    for silence in silences:
        if silence.get("id") != silence_id:
            continue
        if silence.get("comment") != comment:
            raise RuntimeError("restored silence content changed")
        return silence
    return None


def retention_probe():
    flags = get_json(f"{PROMETHEUS_URL}/api/v1/status/flags")["data"]
    return (
        flags.get("storage.tsdb.retention.time") == "1w"
        and flags.get("storage.tsdb.retention.size") == "64MiB"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    backup_dir = Path(tempfile.mkdtemp(prefix="thermoform-state-backup-"))
    comment = f"restore-drill-{PROJECT_NAME}"
    silence_id = None
    remote_query_time = None
    object_store_query_time = None
    fixture_dir = Path(tempfile.mkdtemp(prefix="thermoform-object-store-fixture-"))
    try:
        compose("up", "--detach")
        wait_for("Prometheus and Alertmanager readiness", ready_probe, args.timeout)
        wait_for("two-member Alertmanager cluster", cluster_probe, args.timeout)
        wait_for("both remote-write replicas", remote_series_probe, args.timeout)
        object_store_query_time = upload_object_store_fixture(fixture_dir)
        wait_for(
            "Store Gateway to expose the object-store fixture",
            lambda: object_store_fixture_probe(object_store_query_time),
            args.timeout,
        )
        silence_id = create_silence(comment)
        wait_for(
            "silence replication before backup",
            lambda: restored_silence_probe(silence_id, comment, ALERTMANAGER_2_URL),
            args.timeout,
        )
        refusal = state_tool(
            "backup",
            "--project-name",
            PROJECT_NAME,
            "--output-dir",
            str(backup_dir / "running-refusal"),
            check=False,
            capture_output=True,
        )
        if refusal.returncode == 0 or "mounted by a running container" not in refusal.stderr:
            raise RuntimeError("backup did not refuse a running state owner")
        shutil.rmtree(backup_dir / "running-refusal")
        compose(
            "stop",
            "--timeout",
            "20",
            "thanos-receive",
            "thanos-receive-2",
            "thanos-receive-3",
        )
        wait_for(
            "historical object-store query after all Receive ingesters stop",
            lambda: object_store_fixture_probe(object_store_query_time),
            args.timeout,
        )
        compose(
            "stop",
            "--timeout",
            "20",
            "prometheus",
            "prometheus-2",
            "alertmanager",
            "alertmanager-2",
            "thanos-store",
        )
        remote_query_time = int(time.time()) - 2
        state_tool(
            "backup",
            "--project-name",
            PROJECT_NAME,
            "--output-dir",
            str(backup_dir),
        )
        compose("down", "--volumes", "--remove-orphans")
        compose("create")
        state_tool(
            "restore",
            "--project-name",
            PROJECT_NAME,
            "--input-dir",
            str(backup_dir),
            "--confirm-empty-volumes",
        )
        refusal = state_tool(
            "restore",
            "--project-name",
            PROJECT_NAME,
            "--input-dir",
            str(backup_dir),
            "--confirm-empty-volumes",
            check=False,
            capture_output=True,
        )
        if refusal.returncode == 0 or "is not empty" not in refusal.stderr:
            raise RuntimeError("restore did not refuse populated volumes")
        compose("start")
        wait_for("restored services readiness", ready_probe, args.timeout)
        wait_for("restored two-member cluster", cluster_probe, args.timeout)
        wait_for(
            "restored historical remote-write samples",
            lambda: remote_series_probe(remote_query_time),
            args.timeout,
        )
        wait_for(
            "restored object-store fixture",
            lambda: object_store_fixture_probe(object_store_query_time),
            args.timeout,
        )
        wait_for(
            "restored Alertmanager silence",
            lambda: restored_silence_probe(silence_id, comment),
            args.timeout,
        )
        wait_for(
            "restored Alertmanager silence on the second peer",
            lambda: restored_silence_probe(silence_id, comment, ALERTMANAGER_2_URL),
            args.timeout,
        )
        wait_for("Prometheus retention configuration", retention_probe, args.timeout)
        manifest = json.loads(
            backup_dir.joinpath("manifest.json").read_text(encoding="utf-8")
        )
        print(
            f"PASS: restored silence {silence_id} and verified "
            f"{len(manifest['volumes'])} checksummed volumes, two Prometheus replicas, "
            "three Receive ingesters, and object-store history with 7d/64MB retention."
        )
        return 0
    except (RuntimeError, subprocess.CalledProcessError, OSError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        compose("logs", "--no-color", check=False)
        return 1
    finally:
        if args.keep:
            print(f"State drill retained as project {PROJECT_NAME}")
            print(f"Backup retained at {backup_dir}")
        else:
            compose("down", "--volumes", "--remove-orphans", check=False)
            shutil.rmtree(backup_dir)
            shutil.rmtree(fixture_dir)


if __name__ == "__main__":
    raise SystemExit(main())
