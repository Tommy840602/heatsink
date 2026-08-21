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

**Impact:** Prometheus cannot reach either Alertmanager replica, so CAE recovery alerts cannot be delivered.

1. Check both `alertmanager` containers, `/api/v2/status`, storage availability, and both `thermoform-alertmanager` Prometheus targets.
2. Validate the active configuration with `amtool` and inspect gossip port 9094 connectivity; do not bypass grouping or inhibition merely to clear the alert.
3. Restore at least one replica first, then restore the second and confirm both report two cluster members.
4. Escalate immediately if the API is down while an active OpenFOAM campaign is running.

## ThermoformAlertmanagerClusterDegraded

**Impact:** notification delivery remains available through one replica, but maintenance or another failure would remove the last delivery path.

1. Identify the failed scrape target and inspect that replica's process, volume, configuration, and port 9094 connectivity.
2. Do not restart the healthy peer. Verify it continues receiving new alerts while the failed replica is repaired.
3. Start the repaired peer and wait until both `/api/v2/status` responses report `ready` with two peers.
4. Run the HA failover drill before resolving the incident.

## ThermoformAlertmanagerClusterMembershipMismatch

**Impact:** both HTTP endpoints may be reachable while gossip replication of silences and notification-log entries is incomplete, increasing the risk of duplicate notifications or missed silences.

1. Compare `alertmanager_cluster_members` and `/api/v2/status` on both replicas.
2. Confirm both peers use cluster label `thermoform`, unique peer names, and mutually reachable TCP/UDP port 9094 addresses.
3. Check clock synchronization and cluster logs for peer resolution, reconnect, or settle failures.
4. Create a non-impacting test silence on one peer and verify the same silence ID appears on the other.

## ThermoformAlertDeliveryFailure

**Impact:** Alertmanager accepted an alert but at least one authenticated webhook request failed. It will retry, so the receiver must tolerate duplicate deliveries with the same Alertmanager `groupKey` and alert fingerprints.

1. Inspect `alertmanager_notifications_failed_total` by `integration` and `reason`, plus Alertmanager logs for HTTP status or timeout details.
2. Confirm the destination certificate, DNS, network policy, rate limit, payload limit, and incident-system availability.
3. For HTTP 401/403, compare secret versions and mounts without printing the bearer token. Rotate through the secret manager if its exposure is suspected.
4. Keep the `local-delivery-fallback` route available for delivery-component alerts while the external webhook is impaired.
5. Resolve only after the failure counter stops increasing and an authenticated staging drill reaches the receiver.

## ThermoformPrometheusStorageBudgetHigh

**Impact:** Prometheus blocks, WAL, and head chunks exceed 80% of the configured size-retention limit. Compaction temporarily needs both source and destination blocks, so waiting for the host disk to fill risks failed writes or TSDB corruption.

1. Check the storage-budget panel and break down `prometheus_tsdb_storage_blocks_bytes`, `prometheus_tsdb_wal_storage_size_bytes`, and `prometheus_tsdb_head_chunks_storage_size_bytes`.
2. Confirm the active 30-day/8 GB retention contract through `/api/v1/status/flags` and `prometheus_tsdb_retention_limit_bytes`.
3. Reduce unnecessary high-cardinality series or provision more local disk before increasing retention. Keep 15–20% compaction headroom.
4. Take an offline backup before storage migration; never delete WAL or block directories merely to clear the alert.

## ThermoformPrometheusRetentionNotConfigured

**Impact:** the running Prometheus process reports no size limit, so the deployment no longer guarantees space for WAL and compaction headroom.

1. Inspect the loaded Prometheus configuration, not only the repository file.
2. Restore the Compose arguments `--storage.tsdb.retention.time=30d` and `--storage.tsdb.retention.size=8GB`, then restart Prometheus normally.
3. Verify `prometheus_tsdb_retention_limit_bytes` becomes nonzero and the storage ratio recording rule returns data.

## ThermoformAlertmanagerPersistenceFailure

**Impact:** Alertmanager cannot reliably maintain its silence or notification-log snapshots. A restart could lose silences or cause duplicate notifications even if current webhook delivery still works.

1. Inspect the silence and notification-log maintenance error counters separately and review Alertmanager storage logs.
2. Check volume availability, permissions, free space, and whether `/alertmanager` is still backed by the expected Compose volume.
3. Preserve the current volume and take an offline backup before repair. Do not clear `silences` or `nflog` files to suppress the alert.
4. Run the state restore drill and verify a known silence survives before closing the incident.

## ThermoformPrometheusReplicaDegraded

**Impact:** fewer than two Prometheus replicas are evaluating rules and writing samples, so process-level redundancy is degraded.

1. Identify the missing `instance` in `up{job="thermoform-prometheus"}` and inspect that container's logs and volume.
2. Confirm the surviving replica still evaluates rules and its remote-write queue is moving.
3. Restore the failed replica, then verify both external `replica` labels appear through Thanos Query.

## ThermoformThanosReceiveDown

**Impact:** fewer than two of the three Receive ingesters are healthy, so RF=3 writes cannot reach quorum. Both Prometheus replicas retain local samples while their remote-write queues retry.

1. Check all three readiness endpoints, ring membership, disk capacity, `/thanos/receive` ownership, and WAL errors.
2. Preserve every Receive volume; do not delete a WAL to recover availability.
3. Restore at least two ingesters, then verify both remote-write queues drain without failed-sample growth.

## ThermoformThanosReceiveReplicaDegraded

**Impact:** one of the three RF=3 ingesters is unavailable. Writes remain acknowledged by the two healthy replicas, but another loss removes quorum.

1. Identify missing `instance` labels and distinguish process loss from a scrape-only failure.
2. Confirm both `thanos-receive-a` and `thanos-receive-b` queues; one failed ingress must not stop the other.
3. Query with `dedup=false` and confirm current samples remain on the surviving `receive_replica` values before repairing the failed node.

## ThermoformThanosQueryDown

**Impact:** Grafana and shared historical queries are unavailable even though local collection and remote write may continue.

1. Check Query readiness and its StoreAPI connections to all three Receive ingesters plus `thanos-store:10901`.
2. Query each Prometheus locally while repairing Query, then verify the Grafana datasource returns deduplicated data.

## ThermoformThanosStoreGatewayDown

**Impact:** real-time Receive queries remain available, but historical blocks in the object-store path are absent from Query and Grafana.

1. Inspect Store Gateway readiness, block synchronization, local cache permissions, and object-store mount availability.
2. Do not treat successful current queries as historical recovery; query a known timestamp that exists only in a shipped block.
3. Restart Store Gateway and verify it discovers the expected block count before resolving.

## ThermoformThanosCompactorDown

**Impact:** writes and queries continue, but compaction, downsampling, deletion-mark cleanup, and configured retention are suspended.

1. Confirm that exactly one Compactor is assigned to the bucket and inspect its readiness endpoint and logs.
2. Check scratch-volume capacity and permissions plus bucket list/read/write/delete access through the Compactor workload identity.
3. Restart only after preserving logs and bucket state; verify `up{job="thermoform-thanos-compact"}` returns to one.

## ThermoformThanosCompactorMultipleRunning

**Impact:** more than one Compactor is mutating the same bucket even though its compaction and deletion operations are not concurrency safe.

1. Freeze rollouts and ad-hoc maintenance jobs; identify every Compactor workload and the exact bucket/prefix each one uses.
2. Preserve the designated singleton and stop duplicates gracefully. Do not delete bucket objects while resolving the overlap.
3. Inspect all instance logs and run read-only bucket verification before resuming lifecycle changes; confirm the availability sum is exactly one.

## ThermoformThanosCompactorHalted

**Impact:** Compactor encountered an unrecoverable block condition and deliberately stopped lifecycle processing. Restarting without diagnosis can reproduce the halt.

1. Preserve the bucket, Compactor logs, and affected block IDs. Never start a second Compactor against the same bucket.
2. Inspect overlap, malformed index, partial upload, and deletion-mark evidence with read-only `thanos tools bucket verify` or `inspect` commands.
3. Repair or quarantine blocks only through a reviewed Thanos procedure, then restart the singleton and verify `thanos_compact_halted` remains zero.

## ThermoformThanosCompactionFailure

**Impact:** one or more compaction groups are repeatedly failing, so object growth and retention enforcement can diverge from policy.

1. Break down `thanos_compact_group_compactions_failures_total` by group and correlate it with bucket-operation failures.
2. Check local scratch capacity, network/KMS permissions, and the source blocks named in Compactor logs.
3. Close only after a complete successful loop and a stable Store Gateway historical query.

## ThermoformThanosObjectStoreFailure

**Impact:** a Receive upload, Store Gateway read/list, or Compactor lifecycle operation failed. Local receiver TSDBs may mask the problem until retention removes those blocks.

1. Break down `thanos_objstore_bucket_operation_failures_total` by job, instance, and operation.
2. Check the configured bucket path, ownership, capacity, consistency, and Store Gateway synchronization logs.
3. Preserve the bucket and verify a known historical-only series before closing the incident.

## ThermoformRemoteWriteFailure

**Impact:** Prometheus permanently failed to send one or more samples to Thanos Receive.

1. Correlate failed samples with Receive availability, request errors, queue metrics, and WAL logs on each replica.
2. Confirm local TSDB retention still covers the incident window and record any proven data gap.
3. Close only after failed counters stop increasing and both replica labels are current in Thanos Query.

## ThermoformRemoteWriteBacklogHigh

**Impact:** queued remote-write samples exceed the configured safety threshold and may exhaust the local WAL window.

1. Compare pending samples, shard count, send latency, and Receive ingestion health for each replica.
2. Repair downstream capacity before tuning queue limits; verify the backlog trends to zero.

## Offline backup and restore

The backup tool covers both Prometheus volumes, both Alertmanager volumes, all three Receive TSDB volumes, and `thanos-object-store-data`. Store Gateway cache and Compactor scratch data are excluded because they are rebuilt from the bucket. The tool refuses any covered volume mounted by a running container, writes SHA-256 checksums, validates archive paths, and restores only into empty project-scoped volumes. Schema 1–3 backups remain restorable; newly introduced volumes start empty and converge or rebuild after startup.

1. Identify the exact Compose project with `docker compose ls` and stop both Prometheus replicas, both Alertmanagers, all three Receive ingesters, `thanos-store`, and `thanos-compact` gracefully.
2. Run `python scripts/observability_state.py backup --project-name <project> --output-dir <new-backup-directory>`.
3. Start the services again immediately after backup and copy the backup directory to durable storage.
4. For recovery, preserve or quarantine damaged volumes and let Compose create empty replacements with the same project labels. The tool never deletes or overwrites existing state.
5. With the target services stopped, run `python scripts/observability_state.py restore --project-name <project> --input-dir <backup-directory> --confirm-empty-volumes`, then start the services.
6. Verify both Prometheus replicas and retention, all three Receive replicas, a historical-only Store Gateway query, Alertmanager state, dashboards, and all scrape targets.

## Prometheus HA and remote-write failover

1. Confirm both Prometheus readiness endpoints are healthy and both remote-write queues are moving.
2. Stop the first Prometheus, then emit a new drill phase and prove the second replica evaluates and delivers the new alert.
3. Query the new phase through Thanos and confirm samples continue from `prometheus-2`; old notifications or old samples do not prove continuity.
4. Restart the first replica and confirm both queues drain and Thanos Query's normal deduplicated view contains one logical series.

Normal operation intentionally sends each sample to two Receive ingress URLs; this doubles remote-write traffic but prevents one ingress process from blocking both Prometheus streams.

## Thanos Receive quorum failover

1. Confirm three Receive readiness endpoints and six `dedup=false` copies for a two-Prometheus drill series: every `replica` × `receive_replica` pair.
2. Stop Receive-1, emit a new phase, and verify both Prometheus streams reach Receive-2 and Receive-3 while the RF=3 write quorum remains satisfied.
3. Confirm `ThermoformThanosReceiveReplicaDegraded` fires, `ThermoformThanosReceiveDown` does not, and the normal query still returns one logical series.
4. Restart Receive-1, verify ring readiness and backlog drainage, then confirm three current `receive_replica` values again.

All Prometheus, Receive, Store Gateway, and filesystem bucket volumes still share one Docker host. The filesystem object-store adapter is deterministic for this local reference and CI, but Thanos documents it as a test/demo option; production must use strongly consistent managed object storage and separate failure domains.

## Production S3 cutover

The checked-in `infra/thanos/object-store.yml` remains a local/CI filesystem adapter. A production cutover is complete only when every Receive ingester, Store Gateway, and the singleton Compactor uses the same remote bucket and prefix.

1. Provision a strongly consistent bucket with versioning, encryption, capacity alerts, and an explicitly reviewed lifecycle policy. Do not enable expiration that is shorter than the required metrics retention.
2. Assign workload identities rather than static keys. Receive needs reviewed write/list/read permissions for block shipping, Store Gateway should use read/list-only access, and only the singleton Compactor identity should receive delete permission. Add KMS permissions only when SSE-KMS is selected.
3. Render `.runtime/thanos/object-store.yml` with `scripts/render_thanos_s3_config.py`. Confirm `aws_sdk_auth: true`, `insecure: false`, `signature_version2: false`, and the expected SSE mode; reject any file containing `access_key`, `secret_key`, or `session_token`.
4. Set `THERMOFORM_THANOS_OBJECT_STORE_CONFIG` and run `docker compose config --quiet`. Confirm all three Receive services, Store Gateway, and Compactor mount the same resolved file at `/etc/thanos/object-store.yml`.
5. From the same workload identity and network path, use `thanos tools bucket ls --objstore.config-file=<runtime-file>` to prove list access. Use a disposable prefix or controlled block to prove write/read before changing the live clients.
6. Plan migration of existing filesystem blocks separately. Switching configuration does not copy historical blocks; retain the old volume until a known old timestamp is queryable through Store Gateway from S3.
7. Apply the new configuration to all five clients in one maintenance change. Mixed bucket/prefix configurations split block history and are not an acceptable steady state.
8. Verify Receive upload metrics, Store Gateway synchronization, a historical-only query, `ThermoformThanosObjectStoreFailure`, and rollback access to the preserved filesystem data.

The schema-4 offline tool protects the local filesystem bucket only. It is not a backup of S3. Provider versioning, replication, and restore testing own remote-bucket durability.

## Thanos Compactor retention and lifecycle

Compactor is a singleton for one bucket and is the only component authorized to delete current Thanos block objects. The Compose defaults retain samples indefinitely: raw, 5-minute, and 1-hour retention are all `0d`. Normal compaction may still replace source blocks while preserving their logical samples.

1. Before enabling deletion, choose one retention period of at least 10 days and apply it equally to `THERMOFORM_THANOS_RETENTION_RAW`, `THERMOFORM_THANOS_RETENTION_5M`, and `THERMOFORM_THANOS_RETENTION_1H`. Validate it with `scripts/validate_thanos_retention.py`; the startup guard rejects mismatched, ambiguous, or too-short values.
2. Preserve one Compactor instance across every rollout. Do not use horizontal autoscaling or run an ad-hoc Compactor against the live bucket.
3. Allow Compactor local scratch space for downloading and rewriting blocks. `thanos-compact-data` is rebuildable scratch state and is intentionally excluded from offline backups.
4. Do not configure provider lifecycle rules to expire current Thanos block objects. Lifecycle automation may abort incomplete multipart uploads and expire noncurrent versions only after the reviewed recovery window; Compactor owns current-object retention.
5. Change retention only through a reviewed maintenance change. Reducing it causes irreversible object deletion after blocks completely age out, and failed compaction/downsampling loops prevent retention from running.
6. After rollout, verify Compactor readiness, `thanos_compact_halted == 0`, no new compaction failures, Store Gateway synchronization, and both raw and downsampled historical queries.

## Kubernetes Thanos production rollout

The production base is `infra/kubernetes/observability`. It is a 24-resource Kustomize topology, not a universal cloud deployment: the target environment must supply workload identities, a StorageClass, the object-store Secret, capacity decisions, and any authenticated external gateway.

1. Verify Kubernetes 1.34 or newer, at least three eligible zones and nodes carrying `topology.kubernetes.io/zone`, a working default or overlaid `ReadWriteOnce` StorageClass, and an enforcing `NetworkPolicy` CNI.
2. Render with `kubectl kustomize infra/kubernetes/observability`. Run Kubeconform against Kubernetes 1.34 and `python scripts/validate_kubernetes_observability.py <rendered-file>` before applying an environment overlay.
3. Apply the namespace alone, render the credential-free `object-store.yml`, and create `thermoform-thanos-object-store` from that file. Never commit the rendered file or Secret. Reject `access_key`, `secret_key`, and `session_token` fields.
4. Bind distinct cloud identities to `thanos-receive`, `thanos-store`, and `thanos-compact`; leave `thanos-query` without bucket permissions. Receive needs list/read/write without delete, Store needs list/read only, and only Compactor gets delete. Prove those boundaries from actual pods against a disposable prefix.
5. Label Prometheus namespaces `thermoform.io/metrics-write=true` and intended Query/scrape client namespaces `thermoform.io/metrics-read=true`. Confirm no unlabelled namespace can reach the protected ports.
6. Apply the reviewed overlay. Receive pods must land on three different nodes in three zones. Store and Query replicas must occupy separate nodes. A Pending Receive replica under fewer than three eligible zones is a topology safety signal, not a reason to weaken the base during rollout.
7. Point Prometheus at `http://thanos-receive.thermoform-observability.svc.cluster.local:19291/api/v1/receive`. Point internal Grafana at `http://thanos-query.thermoform-observability.svc.cluster.local:10902`.
8. Verify all three Receive pods report ready, all three fixed hashring endpoints are healthy, RF=3 writes produce three receiver replicas, both Store Gateways synchronize, Query deduplicates `replica` and `receive_replica`, and exactly one Compactor is running.
9. Drain one Receive node through the eviction API. The Receive PDB must preserve two available pods and remote writes must continue. Repeat separately for Store and Query; never combine this with a bucket, identity, or hashring change.
10. Close the change only after remote-write queues drain, bucket failure counters remain stable, a recent query and historical-only query both succeed, and the Compactor remains healthy without halted or failed-group counters.

The PDBs apply to voluntary disruptions only. They cannot protect against direct deletion, simultaneous node loss, broken application configuration, or an unsafe controller rollout. Receive uses a fixed three-member DNS hashring and must not be autoscaled; changing its size requires a separately reviewed hashring migration or Receive Controller architecture. Compactor must remain exactly one replica.

Rollback the workload manifests without deleting PVCs, the object-store Secret, or bucket blocks. The Receive and Compactor StatefulSets retain their claims. If the rollback changes bucket or prefix, stop and prove that old and new history have not split before proceeding; never point a second Compactor at the same bucket as a rollback shortcut.

### Standard Amazon EKS gate

Use `infra/kubernetes/overlays/aws-eks` only with standard EKS managed nodes and the `ebs.csi.aws.com` driver; EKS Auto Mode uses a different storage provisioner and needs a separate reviewed overlay.

1. Render the overlay template, then bind three complete and distinct IRSA role ARNs with `scripts/render_eks_thanos_manifest.py`. Never apply the raw placeholder template.
2. Confirm each role trust policy is restricted to the exact namespace and ServiceAccount subject. Restrict node IMDS so IRSA workloads cannot inherit the broader node role.
3. Apply and review `thermoform-ebs-gp3`, then run `scripts/preflight_eks_thanos.py --context <exact-context>`. The preflight is read-only and must report `ready`, at least three zones, and EBS CSI registration on every eligible node.
4. Validate the 25-resource output with Kubeconform and `scripts/validate_kubernetes_observability.py`. Confirm only Receive and Compactor claims use retained gp3 volumes; Store cache is rebuildable local state.
5. Create the credential-free object-store Secret before applying workloads. After admission, verify each bucket client received the expected web-identity environment and Query received none.
6. Complete the general Kubernetes rollout, node-drain, query, remote-write recovery, and Compactor checks above before enabling production traffic.

### Terraform infrastructure gate

`infra/terraform/environments/production` consumes the AWS storage module. Its backend uses an independently bootstrapped encrypted/versioned S3 bucket and native `.tflock` locking; state and Thanos data must use different buckets. Follow the environment README for the exact bootstrap permissions and GitHub settings.

1. Validate `infra/aws-bootstrap/production-terraform-plan.yml` with pinned `cfn-lint`, `scripts/validate_aws_bootstrap.py`, and the audit read-only contract. Create a CloudFormation `CREATE` change set through a separately authenticated bootstrap identity, but do not execute it yet. Never manage the state foundation from the state it stores.
2. Before the change set, verify whether the account-wide GitHub provider already exists and obtain the repository owner/repository IDs from the live GitHub API. This repository requires the immutable subject `repo:Tommy840602@84989346/heatsink@1341254721:environment:production-plan`; a transfer, rename, replacement, or custom subject configuration requires revalidation.
3. From the exact reviewed commit, run `scripts/audit_aws_bootstrap.py change-set` with explicit account, region, stack/change-set names, buckets, OIDC subject, and provider choice. Stop unless it reports `ready-for-human-review`; Modify/Remove/Import/replacement, parameter mismatch, extra resource, template mismatch, or truncation is forbidden.
4. A separate authorized operator may execute the reviewed change set. Enable stack termination protection, then run `scripts/audit_aws_bootstrap.py deployed` through an audit identity that has only the documented get/list/describe/simulate permissions. Stop unless stack, bucket, KMS, OIDC, role trust/policies, lifecycle absence, and IAM allowed/denied simulations pass.
5. Protect the GitHub `production-plan` Environment with required reviewers, self-review prevention where available, and deployment restricted to protected `main`. Its OIDC role trust must use audience `sts.amazonaws.com`, the exact live Environment subject, and `StringEquals` only.
6. Configure only Environment variables from reviewed bootstrap outputs; store no access key. The plan role may Get/Put the exact state object, Get/Put/Delete only its exact `.tflock`, and read managed resources. It must not delete state or mutate IAM, KMS, or the Thanos bucket. Versioning is the recovery control for authorized or compromised state overwrite.
7. Run Terraform 1.15.8 formatting/validation and both Terraform contract validators locally or in CI. These checks use no AWS credentials.
8. Dispatch `Production Terraform plan` from `main`, enter that exact 40-character commit SHA, select `PLAN_ONLY`, and approve the Environment deployment. Any ref, SHA, account, region, role, bucket, prefix, or OIDC mismatch fails before AWS authentication.
9. Review the value-free job summary. Delete, replacement, dependency-lock drift, and more than 50 changed resources are stop conditions. The workflow has no apply step, uploads no saved plan, and removes its temporary binary plan, JSON, and log even after failure.
10. Confirm all public-access blocks, BucketOwnerEnforced ownership, versioning, KMS default encryption, bucket keys, TLS deny, `prevent_destroy`, and `force_destroy = false` remain in the plan.
11. Confirm current objects have no S3 expiration. Receive has list/get/put without delete, Store has list/get only, and Compactor alone has list/get/put/delete; every IRSA trust uses exact `aud` and `sub` equality.
12. Treat this plan as review evidence only. Applying it requires a future separately reviewed role, workflow, approval policy, and explicit change authorization. After an authorized apply exists, feed outputs into the S3 and EKS renderers; never copy credentials, state, or plan files into `.runtime` or Git.

### Targeted staging eviction drill

Run the drill only in staging with at least one EBS CSI-capable spare node in the selected Receive pod's zone. Plan mode is read-only:

```bash
python scripts/run_eks_thanos_staging_drill.py \
  --context <staging-context> \
  --pod thanos-receive-0
```

Review the returned pod, node, zone, and spare node. Execute only after confirming there is no concurrent maintenance, bucket migration, retention change, or active incident:

```bash
python scripts/run_eks_thanos_staging_drill.py \
  --context <staging-context> \
  --pod thanos-receive-0 \
  --execute-eviction \
  --confirm-context <staging-context> \
  --confirm-node <node-from-plan>
```

Execution cordons only the selected node, submits one `policy/v1` Eviction for the Receive pod, waits for a new UID to become Ready on a different node in the same zone, and uncordons the original node in a `finally` path. It does not drain unrelated Pods. Independently confirm the Receive PDB preserved two available replicas, remote-write continued, backlog returned to zero, and all three Receive replicas recovered before closing the drill.

If the process is force-killed or loses cluster access after cordoning, manually verify and recover the exact planned node with `kubectl --context <staging-context> uncordon <node-from-plan>` before any further maintenance.

## Alertmanager HA failover

1. Confirm both Alertmanager `/api/v2/status` endpoints report `ready` with two peers and Prometheus targets both replicas directly.
2. Create a test silence on one peer and verify the identical silence ID on the other peer.
3. Stop only the first Alertmanager and confirm `ThermoformAlertmanagerClusterDegraded` fires while alert delivery remains available.
4. Emit a new safety-labeled test alert after the stop and verify the surviving peer delivers it. Re-observing an old notification alone does not prove failover.
5. Restart the first peer, wait for two-member convergence, and verify the silence plus notification log converge before resolving.
6. Gossip is fail-open: during a network partition, duplicate notifications are preferable to losing a critical notification.

The Compose peers share one host and an unencrypted private Docker network. A cross-host deployment must place replicas in distinct failure domains and protect gossip traffic with the Alertmanager cluster TLS configuration; this local pair alone does not survive host loss.

## External webhook deployment

1. Store the bearer token outside Git as `thermoform_alert_webhook_token`, set its directory to `0750` and file to `0640`, and export its group ID through `THERMOFORM_ALERT_SECRET_GID` so the non-root container can read it.
2. Render the runtime configuration with `scripts/render_alertmanager_runtime.py`; production URLs must use HTTPS and cannot contain credentials or fragments.
3. Set `THERMOFORM_ALERTMANAGER_CONFIG` to the rendered file and `THERMOFORM_ALERT_SECRET_DIR` to its separately managed secret directory before starting Compose.
4. Validate the rendered configuration with `amtool`, then run `scripts/run_observability_alert_drill.py` against the isolated fixture before enabling a real receiver.
5. The receiver must deduplicate Alertmanager retries using `groupKey` and individual alert fingerprints.

## Recovery verification

- Both Prometheus replicas target the API, both Alertmanagers, three Receive ingesters, Query, Store Gateway, and Compactor; all twenty-eight alert rules are loaded.
- Alertmanager shows the expected grouped receiver and no unexpected inhibited alerts.
- `/api/v1/cae/observability` reports `healthy`, zero stale heartbeats, and a recent watchdog.
- A repaired or retried attempt has one append-only terminal event and intact lineage.
- Grafana shows at least two fresh watchdog intervals after recovery.
- The 30-day recovery availability is at or above 99.5%, or the remaining error budget and follow-up mitigation are recorded in the incident.

For production delivery, use the runtime renderer and secret-directory mounts above. Never edit a bearer token into Alertmanager YAML or commit receiver credentials.
