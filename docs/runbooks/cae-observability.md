# CAE recovery observability runbook

This runbook covers alerts for the durable CAE checkpoint-resume recovery path. The reduced-order simulator is not CFD, and an alert must never be resolved by marking an unvalidated solver response as publishable.

## Before you start

1. Open the `CAE Resume Observability` Grafana dashboard and the Alertmanager UI.
2. Check `docker compose ps`, then inspect `backend`, `worker`, `watchdog`, `redis`, and `cae-worker` logs for the alert window.
3. Read `/api/v1/cae/observability`, `/api/v1/cae/resume-watchdog`, and `/api/v1/cae/resume-attempts` before changing state.
4. Preserve `/data` and every checkpoint ZIP. Do not delete Redis jobs, durable artifacts, or work directories during diagnosis.
5. Silence only the affected alert labels, include the incident reference, and set the shortest practical expiry.

## ThermoformCaeApiDown

**Impact:** Prometheus cannot observe recovery state, and Alertmanager suppresses dependent CAE alerts from the same instance to prevent a notification storm.

1. Request `/api/v1/health` and `/metrics` directly from the backend network.
2. Check backend health, restarts, filesystem permissions, and whether the shared artifact volume is mounted at `/data`.
3. If artifact scanning is slow, inspect artifact count and corrupt JSON separately; do not remove artifacts to restore the metric endpoint.
4. Restore FastAPI first, then verify `up{job="thermoform-api"} == 1` and that the dependent alerts settle.

Escalate immediately if the API is down while an active OpenFOAM campaign is running or if `/data` is unavailable.

## ThermoformCaeWatchdogMissing

**Impact:** no durable scheduled audit has been observed since startup, so missing RQ jobs will not be repaired without a browser reconciliation.

1. Confirm the `watchdog` container is running `rq cron app.cron_config` and can reach Redis.
2. Confirm a general `thermoform` worker is active; RQ Cron schedules the job but the worker executes it.
3. Verify both services mount the same `thermoform-artifacts:/data` volume as FastAPI.
4. Inspect the general worker for `run_resume_watchdog` failures and confirm a new `resume-watchdog-report.json` appears.
5. Resolve only after `/api/v1/cae/resume-watchdog` returns a recent report.

## ThermoformCaeWatchdogStale

**Impact:** the last durable audit is older than three minutes; active resume attempts may no longer be reconciled automatically.

1. Compare the report timestamp with the RQ Cron interval and Prometheus scrape time.
2. Check Redis latency, the general worker queue depth, and watchdog job failures.
3. Verify the scheduler and worker clocks are synchronized.
4. If the queue is congested, restore general worker capacity without moving CAE jobs onto the general queue.
5. Confirm two consecutive fresh watchdog reports before closing the incident.

## ThermoformCaeResumeHeartbeatStale

**Impact:** a nonterminal resume attempt still claims an active worker lease but has not refreshed it within the configured threshold.

1. Use the resume-attempt API and `/data/cae/resume_*/resume-heartbeat.json` to identify the oldest active heartbeat.
2. Check the corresponding `thermoform-cae` RQ job and CAE worker process before declaring it orphaned.
3. Inspect OpenFOAM logs, disk capacity, checkpoint writes, and worker termination signals.
4. Never create a failed event manually. Allow the watchdog grace policy to reconcile the attempt from heartbeat, RQ, or successor artifacts.
5. Retry only after the durable lifecycle becomes terminal `failed` and React exposes the controlled retry action.

## ThermoformCaeOrphanRepairDetected

**Impact:** the latest watchdog audit found an expired missing RQ job and appended an `orphaned_job_missing` failure.

1. Read the latest watchdog report and identify every attempt whose reason is `orphaned_job_missing`.
2. Confirm there is no successor campaign report and no live worker before retrying.
3. Preserve the failed attempt, heartbeat, dispatch, and checkpoint artifacts for incident analysis.
4. Use the controlled retry endpoint or React action; never submit a forged generic CAE job.
5. Investigate Redis eviction, worker loss, or deployment timing if multiple orphan repairs occur together.

## ThermoformCaeRetryFailed

**Impact:** a controlled retry has reached a durable failed state and still requires engineering review.

1. Follow the retry/root lineage to the original parent campaign and immutable checkpoint.
2. Inspect the failed lifecycle event, worker error, OpenFOAM log, resource limits, and checkpoint compatibility.
3. Do not retry repeatedly until the failure cause is understood; deduplication prevents identical concurrent submissions but not an intentional later retry.
4. If the checkpoint or case fingerprint is invalid, return to case generation instead of bypassing validation.
5. Keep `results_available=false` unless convergence, energy balance, and mesh-independence gates all pass.

## ThermoformCaeRecoverySloFastBurn

**Impact:** both the five-minute and one-hour windows are consuming the 99.5% recovery-availability error budget faster than 14.4x. If sustained, the thirty-day budget will be exhausted quickly.

1. Treat this as a live recovery-path incident and correlate the alert start with API availability, watchdog age, stale heartbeats, Redis failures, and deployments.
2. Confirm which SLI component is zero: `up{job="thermoform-api"}` or `thermoform_cae_observability_healthy`.
3. Restore the API, scheduler, general worker, Redis, or shared artifact volume that is breaking the durable recovery path.
4. Do not clear the alert by fabricating a watchdog report, lifecycle event, or successful CAE result.
5. Escalate until both short windows fall below the 14.4x burn threshold and new watchdog intervals remain healthy.

## ThermoformCaeRecoverySloSlowBurn

**Impact:** both the thirty-minute and six-hour windows are consuming the 99.5% recovery-availability error budget faster than 6x, indicating persistent degradation that may not create a single obvious outage.

1. Review the thirty-day availability and remaining error-budget panels before scheduling risky CAE or platform changes.
2. Compare recurring unhealthy periods with queue depth, watchdog runtime, artifact scan duration, storage pressure, and worker capacity.
3. Fix the recurring cause; silencing or restarting Prometheus does not restore the SLI and can hide additional budget loss.
4. Validate two healthy six-hour-window evaluations before closing a recurring incident.

## ThermoformCaeRecoverySliMissing

**Impact:** Prometheus cannot calculate the composite recovery SLI, so neither burn-rate alerts nor the remaining error budget are trustworthy.

1. Confirm the `thermoform-api` target exists and inspect Prometheus target discovery and rule-evaluation errors.
2. Check that both `up{job="thermoform-api"}` and `thermoform_cae_observability_healthy{job="thermoform-api"}` have current samples with matching `job` and `instance` labels.
3. Validate that `infra/prometheus/slo.yml` is loaded and the `thermoform-cae-slo-recording` group is healthy.
4. Restore scrape or rule evaluation before interpreting the dashboard's availability and error-budget panels.

## ThermoformAlertmanagerDown

**Impact:** Prometheus cannot hand off CAE recovery alerts or observe external notification health. Existing alerts may remain visible in Prometheus, but operators cannot rely on Alertmanager grouping, inhibition, silencing, or delivery.

1. Check the `alertmanager` container, `/api/v2/status`, storage availability, and the `thermoform-alertmanager` Prometheus target.
2. Validate the active configuration with `amtool`; if external delivery was just enabled, confirm both runtime mount paths resolve inside the container.
3. Restore Alertmanager before changing CAE recovery state. Do not mark engineering attempts successful to suppress alerts.
4. After recovery, verify Prometheus can post an alert and that Alertmanager reports the expected receiver.

## ThermoformAlertDeliveryFailure

**Impact:** Alertmanager accepted an alert but at least one authenticated webhook request failed. It will retry, so the receiver must tolerate duplicate deliveries with the same Alertmanager `groupKey` and alert fingerprints.

1. Inspect `alertmanager_notifications_failed_total` by `integration` and `reason`, plus Alertmanager logs for HTTP status or timeout details.
2. Confirm the destination certificate, DNS, network policy, rate limit, payload limit, and incident-system availability.
3. For HTTP 401/403, compare secret versions and mounts without printing the bearer token. Rotate through the secret manager if its exposure is suspected.
4. Keep the `local-delivery-fallback` route available for delivery-component alerts while the external webhook is impaired.
5. Resolve only after the failure counter stops increasing and an authenticated staging drill reaches the receiver.

## External webhook deployment

1. Store the bearer token outside Git as `thermoform_alert_webhook_token`, set its directory to `0750` and file to `0640`, and export its group ID through `THERMOFORM_ALERT_SECRET_GID` so the non-root container can read it.
2. Render the runtime configuration with `scripts/render_alertmanager_runtime.py`; production URLs must use HTTPS and cannot contain credentials or fragments.
3. Set `THERMOFORM_ALERTMANAGER_CONFIG` to the rendered file and `THERMOFORM_ALERT_SECRET_DIR` to its separately managed secret directory before starting Compose.
4. Validate the rendered configuration with `amtool`, then run `scripts/run_observability_alert_drill.py` against the isolated fixture before enabling a real receiver.
5. The receiver must deduplicate Alertmanager retries using `groupKey` and individual alert fingerprints.

## Recovery verification

- Prometheus targets `thermoform-api` and `thermoform-alertmanager` are up and all eleven alert rules are loaded.
- Alertmanager shows the expected grouped receiver and no unexpected inhibited alerts.
- `/api/v1/cae/observability` reports `healthy`, zero stale heartbeats, and a recent watchdog.
- A repaired or retried attempt has one append-only terminal event and intact lineage.
- Grafana shows at least two fresh watchdog intervals after recovery.
- The 30-day recovery availability is at or above 99.5%, or the remaining error budget and follow-up mitigation are recorded in the incident.

For production delivery, use the runtime renderer and secret-directory mounts above. Never edit a bearer token into Alertmanager YAML or commit receiver credentials.
