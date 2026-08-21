# Thermoform — AI-Assisted Thermal Design Platform

Thermoform is a separated React + FastAPI engineering application for heat-sink design exploration. Phase 1 is an executable DOE → physics simulation → statistical analysis → surrogate training → optimization loop, with immutable dataset/model artifacts and a React digital-twin interface.

Phase 2 adds iterative Bayesian Optimization and FreeCAD-compatible parametric CAD artifacts. A STEP file is reported only when a real `FreeCADCmd` execution succeeds; otherwise the system returns the runnable FreeCAD script plus an explicitly identified preview STL.

Phase 3 moves long workflows to Redis/RQ workers and adds a traceable OpenFOAM CHT case handoff. Case generation is never reported as a CFD result: mesh validation, a successful solver run, convergence checks, and result parsing are separate states.

Phase 3.1 adds an official `multiRegionHeater` environment benchmark plus machine-readable mesh quality, convergence, energy-balance, and response-metric acceptance gates. Passing the tutorial proves the OpenFOAM runtime path only; it does not create a heat-sink CFD result.

Phase 3.2 replaces the overlapping fallback boxes with a watertight fused heat-sink surface, encloses it inside the flow domain, and defines explicit `fluid`/`solid` snappyHexMesh regions. Design CAE packaging and benchmark runs are both isolated on the OpenFOAM worker queue; thermal fields and design-result acceptance remain separate gates.

Phase 3.3 adds the `cae_mesh` worker task and per-region mesh qualification. The production candidate resolves a 0.5 mm fin with approximately two cells through its thickness and rejects low-determinant cells while reporting configurable non-orthogonality, skewness, and concave-cell percentage limits separately for fluid and solid regions.

Phase 3.4 packages compressible laminar air, isotropic aluminum, inlet/outlet fields, an implicit coupled temperature interface, and an absolute solid-region heat source. The isolated `cae_smoke` task executes one 10 µs `chtMultiRegionFoam` step to validate the field/material contract without presenting the transient state as a converged design result.

Phase 3.5 adds solver-native response probes for solid Tmax, inlet/outlet area-average pressure, and integrated solid-interface heat flux. Readiness requires at least five samples, stable Tmax and pressure drop, converged residuals, energy imbalance within 5%, and a non-smoke execution mode; smoke reports expose the parsed values only as provisional diagnostics.

Phase 3.6 adds the resumable `cae_solve` production contract. Each run can restore only a checkpoint with the same design and boundary-condition fingerprint, advances from `latestTime`, and emits a new immutable checkpoint. Multi-region MPI runs generate matching interface face sets, constrain both sides to the same processor, reconstruct the latest written time, and still publish no CFD response until every readiness gate passes.

Phase 3.7 adds `cae_campaign` for automatic checkpoint chaining with target-time, segment-count, and wall-clock budgets plus cooperative cancellation at safe checkpoint boundaries. Mesh profiles are now part of the case fingerprint (`coarse=0.8×`, `medium=1.0×`, `fine=1.25×`), and `cae_mesh_study` is the final publication gate: all three campaigns must converge and the medium-to-fine Tmax and pressure-drop changes must stay within configured limits.

Phase 3.8 exposes those operations in React. The CAE Operations workspace configures and polls one resumable campaign at a time, requests cooperative cancellation, renders checkpoint and stop-reason history, tracks coarse/medium/fine convergence separately, and enables the mesh-independence publication gate only after all three campaigns have numerically converged.

Phase 3.9 makes CAE operations recoverable across browser sessions. FastAPI exposes read-only campaign and mesh-study indexes plus immutable report detail endpoints; React persists the active job ID, reconnects to RQ after a reload, restores the newest report for every mesh profile, and lets engineers inspect older checkpoint timelines without rerunning OpenFOAM.

Phase 3.10 adds guarded continuation from recovered checkpoints. A resume preflight validates the current design and boundary-condition fingerprint, mesh profile, solve report, checkpoint metadata, stored latest time, and a strictly advancing target time before React is allowed to queue a successor `cae_campaign`.

Phase 3.11 closes the client-side preflight-to-queue race. A single FastAPI resume operation validates the immutable checkpoint and immediately enqueues the successor on `thermoform-cae`; parent campaign, checkpoint, target time, and a deterministic resume-attempt ID travel together in RQ metadata and the successor campaign report.

Phase 3.12 makes that resume operation idempotent across repeated clicks, browser sessions, and concurrent callers. A Redis lock plus deterministic RQ job ID reuses an active attempt, a durable immutable dispatch record survives job expiry, and an existing successor campaign report prevents accidental OpenFOAM reruns. React exposes the complete parent → checkpoint → successor lineage.

Phase 3.13 adds an append-only resume-attempt lifecycle (`queued`, `started`, `failed`, `completed`, or `cancelled`) and a controlled retry contract. Only a terminal failed attempt may be retried; its immutable parent, checkpoint, and solver settings are reused while a new attempt, job, and successor campaign identity are issued. Repeated retry requests deduplicate to that same retry attempt, and React renders the event trail with the retry action only when the backend permits it.

Phase 3.14 reconciles durable resume history with RQ after worker or Redis job-record loss. Known active jobs remain untouched, explicit RQ terminal states repair a missing terminal event immediately, and a missing job becomes an append-only orphaned failure only after a runtime-aware grace period covering the configured total campaign budget, one final segment, and a safety buffer. React runs this audit before restoring history, reports repaired/active/grace counts, and exposes the existing controlled retry only after reconciliation records the failure.

Phase 3.15 removes the browser dependency from that recovery path. Resume workers maintain an atomic durable heartbeat every 30 seconds while OpenFOAM runs, and an RQ Cron scheduler enqueues the watchdog on the general worker every minute. The watchdog reconciles heartbeat leases, RQ state, immutable successor reports, and lifecycle events, then persists its own immutable report. React shows both its immediate reconciliation result and the last server-scheduled audit.

Phase 3.16 adds durable CAE recovery observability. FastAPI derives low-cardinality Prometheus metrics from shared resume, heartbeat, event, and watchdog artifacts, so process restarts do not erase the monitoring state. Prometheus evaluates alerts for a missing or stale watchdog, stale worker heartbeats, orphan repairs, and failed retries; a provisioned Grafana dashboard and the React CAE Operations panel expose the same health contract.

Phase 3.17 makes those alerts operational. Alertmanager groups and deduplicates CAE recovery incidents, routes critical and warning severities with separate repeat intervals, and inhibits dependent symptoms while FastAPI or the watchdog is unavailable. Every rule links to a recovery runbook, a secret-file webhook example keeps receiver credentials out of Git, and GitHub Actions validates Compose, Prometheus rules, Alertmanager routes, and Grafana JSON on every relevant pull request.

Phase 3.18 defines a 99.5% thirty-day availability SLO for the complete CAE recovery path. Prometheus records composite API-plus-durable-health availability, remaining error budget, and multi-window burn rates; fast, slow, and missing-SLI alerts link to the runbook. Grafana exposes the budget directly, while an isolated Compose drill proves that a controlled missing-watchdog fixture reaches the production Alertmanager warning route.

Phase 3.19 makes external notification delivery deployable. A strict runtime renderer accepts only credential-free HTTPS endpoints, verifies a separately mounted bearer-token file, and never copies the token into Alertmanager YAML. The token uses group-scoped read access for Alertmanager's non-root container instead of making it world-readable or running the container as root. Prometheus now monitors Alertmanager itself and native webhook failure counters, Grafana exposes delivery health, and the isolated drill proves the full authenticated metrics fixture → Prometheus → Alertmanager → webhook receiver path.

Phase 3.20 establishes observability-state durability. Prometheus keeps at most 30 days and 8 GB of TSDB data, bounding local storage while reserving host capacity for compaction headroom, and Alertmanager explicitly retains state for 120 hours. Native storage and snapshot-maintenance metrics drive capacity, retention-drift, and persistence alerts. An offline-only backup tool archives the project-scoped Prometheus and Alertmanager volumes with SHA-256 manifests and restores only into empty volumes; a real drill proves an Alertmanager silence survives volume destruction and reconstruction.

Phase 3.21 removes the single Alertmanager process from the notification path. Prometheus sends every alert directly to two gossip-clustered Alertmanager replicas; silences and notification-log state converge between their independent volumes, while degraded reachability and incomplete membership alert separately from total loss. The HA drill creates a silence on one peer, verifies it on the other, stops the primary, and proves a new alert still reaches the authenticated receiver. Prometheus also carries stable `cluster` and unique `replica` external labels and removes `replica` only from alerts, establishing the identity contract required by a future Prometheus pair and remote storage without claiming that remote write is already deployed. Both replicas still share one Docker host, so host-level failure-domain redundancy is intentionally not claimed.

Phase 3.22 adds a second Prometheus rule evaluator and a durable shared remote-write path. Both replicas write uniquely labeled samples to Thanos Receive; Thanos Query deduplicates on `replica` and is Grafana's datasource. New alerts and dashboard panels cover replica loss, Receive/Query availability, failed samples, and queue backlog. The drill stops the primary Prometheus, proves the secondary evaluates and delivers a newly created alert, and verifies new remote samples continue from only that replica. Offline backup schema 3 now protects both Prometheus volumes, both Alertmanager volumes, and Receive state. Receive is a single local persistent service without object storage, and every component shares one Docker host, so remote-store or host-level HA is not claimed.

Phase 3.23 replaces the single Receive process with a three-ingester Ketama ring and RF=3 quorum writes. Each Prometheus fans out to two ingress URLs, Thanos Query deduplicates both Prometheus and Receive replica labels, and Store Gateway reads long-term blocks from a shared object-store interface. New alerts distinguish degraded replication from lost write quorum, Store Gateway loss, and bucket-operation failure. The HA drill proves new samples and alerts survive one ingester, one Prometheus, and one Alertmanager failure in sequence; backup schema 4 protects eight source-of-truth volumes and verifies an object-store-only historical series after all ingesters stop. The local stack uses Thanos's filesystem bucket adapter for deterministic CI, so it remains a same-host reference rather than production S3 or cross-failure-domain HA.

Phase 3.24 adds a guarded production S3 cutover contract without weakening the deterministic local stack. A strict renderer emits only TLS/signature-v4, workload-identity (`aws_sdk_auth`) configuration with SSE-S3 or optional SSE-KMS; it has no static credential inputs and rejects unsafe bucket, endpoint, prefix, and KMS values. One Compose override path feeds the same runtime file to all three Receive ingesters and Store Gateway, while CI proves the rendered file contains no access-key, secret-key, or session-token fields. Bucket provisioning, IAM/KMS, migration, lifecycle policy, Compactor, and cross-failure-domain scheduling remain explicit deployment responsibilities.

> The built-in physics simulator is a reduced-order engineering model, not CFD or CAE.

## Architecture

```text
Browser
  └─ React frontend (:3000)
       └─ JavaScript HTTP client
            └─ FastAPI backend (:8000)
                 ├─ Redis job queue → isolated RQ worker
                 ├─ RQ Cron watchdog → durable resume heartbeat audit
                 ├─ Prometheus HA pair + bounded local TSDB (:9090/:9091)
                 ├─ Thanos Receive RF=3 ring + Store Gateway + Query (:10909–:10912/:10902)
                 ├─ Alertmanager HA pair + authenticated delivery (:9093/:9095)
                 ├─ provisioned Grafana recovery dashboard (:3001)
                 ├─ design validation + standard CCD / BBD / LHS
                 ├─ deterministic thermal, pressure-drop, and mass simulation
                 ├─ quadratic RSM, ANOVA, and residual diagnostics
                 ├─ RSM / Random Forest / XGBoost / GPR evaluation
                 ├─ differential evolution + NSGA-II optimization
                 ├─ EI / PI / UCB Bayesian learning loop
                 ├─ FreeCAD script + STEP/STL artifact adapter
                 ├─ OpenFOAM CHT case packaging and guarded execution
                 ├─ OpenFOAM v2312 tutorial benchmark + acceptance parser
                 └─ versioned dataset and model artifacts
```

```text
frontend/   React 19, JavaScript/JSX, Vinext/Vite, responsive engineering and CAE operations UI
backend/    FastAPI, Pydantic, pyDOE3, SciPy, scikit-learn, XGBoost, pymoo
```

## One-command startup

```bash
docker compose up --build
```

Start the pinned OpenFOAM worker as an explicit CAE profile:

```bash
docker compose --profile cae up --build
```

- Frontend: http://localhost:3000
- FastAPI docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/v1/health
- Prometheus: http://localhost:9090
- Prometheus replica 2: http://localhost:9091
- Thanos Query: http://localhost:10902
- Thanos Receive health/API: http://localhost:10909
- Thanos Receive replicas 2/3: http://localhost:10910 and http://localhost:10911
- Thanos Store Gateway: http://localhost:10912
- Alertmanager replica 1: http://localhost:9093
- Alertmanager replica 2: http://localhost:9095
- Grafana: http://localhost:3001 (`admin` / `thermoform` for local development)
- Redis and the RQ worker run as internal Compose services.
- The watchdog service schedules server-side resume reconciliation every 60 seconds; it does not wait for a browser session.
- Both Prometheus replicas scrape durable CAE recovery metrics, each other, the three-ingester Thanos tier, and both Alertmanagers every 15 seconds. Each sends alerts to both peers and remote-writes to two Receive ingress URLs; RF=3 requires two ingesters to acknowledge a write. They evaluate the 99.5% recovery SLO, notification, storage, quorum, object-store, and process HA failures.
- Each Prometheus retains at most 30 days and 8 GB locally; each Receive retains 30 days locally and ships blocks through the configured object-store interface; Alertmanager retains state for 120 hours. Grafana queries Thanos Query across real-time Receive APIs and Store Gateway. Every alert links to `docs/runbooks/cae-observability.md`.
- The optional `cae-worker` runs the official OpenCFD v2312 amd64 packages and listens only on `thermoform-cae`.

## Local development

Backend:

```bash
cd backend
python -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/uvicorn app.main:app --reload
```

Frontend, in another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Run the isolated HA and alert-routing drill (uses only `19090`-series loopback ports, then removes its own Compose project and volume):

```bash
python scripts/run_observability_alert_drill.py
```

Prepare authenticated production webhook delivery without storing credentials in Git:

```bash
mkdir -p .runtime/alertmanager-secrets
chmod 750 .runtime/alertmanager-secrets
install -m 640 /path/from/your/secret-manager/token .runtime/alertmanager-secrets/thermoform_alert_webhook_token
python scripts/render_alertmanager_runtime.py \
  --webhook-url https://incident.example.net/v1/thermoform \
  --secret-dir .runtime/alertmanager-secrets \
  --output .runtime/alertmanager.yml
THERMOFORM_ALERTMANAGER_CONFIG=.runtime/alertmanager.yml \
THERMOFORM_ALERT_SECRET_DIR=.runtime/alertmanager-secrets \
THERMOFORM_ALERT_SECRET_GID="$(id -g)" \
docker compose up --build
```

Production webhook URLs must use HTTPS. The renderer rejects credentials embedded in URLs, fragments, empty tokens, group-writable tokens, and token files readable by other users. The supplemental GID lets Alertmanager's `nobody` user read the group-scoped token without running the container as root.

Prepare a production S3 object-store file without embedding cloud credentials:

```bash
mkdir -p .runtime/thanos
python scripts/render_thanos_s3_config.py \
  --bucket thermoform-metrics-prod \
  --endpoint s3.ap-northeast-1.amazonaws.com \
  --region ap-northeast-1 \
  --prefix thermoform/metrics \
  --output .runtime/thanos/object-store.yml
THERMOFORM_THANOS_OBJECT_STORE_CONFIG=.runtime/thanos/object-store.yml \
  docker compose config --quiet
```

The target platform must inject an IAM task/instance role or projected web identity through the AWS SDK credential chain. Never put access keys in this file or `.env`. Validate the bucket through the same workload identity and follow the production cutover checklist in `docs/runbooks/cae-observability.md` before restarting all Receive and Store Gateway processes with the new path.

Exercise a real offline backup and restore against isolated named volumes and an Alertmanager silence:

```bash
python scripts/run_observability_state_drill.py
```

For an operational backup, first obtain the exact project name from `docker compose ls`, then stop only the state owners and archive them:

```bash
docker compose stop prometheus prometheus-2 alertmanager alertmanager-2 thanos-receive thanos-receive-2 thanos-receive-3 thanos-store
python scripts/observability_state.py backup \
  --project-name heat-sink \
  --output-dir /secure/backups/thermoform-observability-YYYYMMDD
docker compose start prometheus prometheus-2 alertmanager alertmanager-2 thanos-receive thanos-receive-2 thanos-receive-3 thanos-store
```

Restore requires stopped services, an intact checksum manifest, the explicit `--confirm-empty-volumes` flag, and empty replacement volumes. It never deletes or overwrites an existing volume.

Copy each `.env.example` to `.env` when overriding local defaults.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | Service readiness and simulator version |
| `GET` | `/api/v1/overview` | Dashboard summary |
| `POST` | `/api/v1/designs/validate` | Validate engineering bounds |
| `POST` | `/api/v1/doe/generate` | Generate CCD, BBD, or LHS matrix |
| `POST` | `/api/v1/simulations/predict` | Predict one design |
| `POST` | `/api/v1/simulations/run` | Simulate a reproducible batch |
| `POST` | `/api/v1/analysis/run` | Fit quadratic RSM; return ANOVA and diagnostics |
| `POST` | `/api/v1/models/train` | Train and cross-validate four surrogate families |
| `GET` | `/api/v1/models/{model_id}/metrics` | Read immutable model metrics |
| `POST` | `/api/v1/models/{model_id}/predict` | Predict with the selected persisted surrogate |
| `POST` | `/api/v1/optimizations/run` | Run single- or multi-objective optimization |
| `POST` | `/api/v1/workflows/phase1/run` | Execute the complete Phase 1 closed loop |
| `POST` | `/api/v1/bayesian/propose` | Rank the next experiment with EI, PI, or UCB |
| `POST` | `/api/v1/workflows/phase2/run` | Propose, simulate, update, retrain, and prepare CAD |
| `POST` | `/api/v1/cad/generate` | Generate traceable FreeCAD script and CAD artifacts |
| `GET` | `/api/v1/cad/{cad_id}/artifacts/{filename}` | Download a generated CAD artifact |
| `POST` | `/api/v1/jobs` | Queue Phase 1, Phase 2, `cae`, `cae_mesh`, `cae_smoke`, `cae_solve`, `cae_campaign`, `cae_mesh_study`, or `cae_benchmark` work and return `202` |
| `GET` | `/api/v1/jobs/{job_id}` | Poll queue state and retrieve a completed result |
| `POST` | `/api/v1/jobs/{job_id}/cancel` | Request cooperative cancellation; active CAE campaigns stop after the current checkpoint |
| `POST` | `/api/v1/cae/cases` | Prepare an OpenFOAM case synchronously for integration use |
| `GET` | `/api/v1/cae/campaigns` | List newest-first immutable CAE campaign summaries |
| `GET` | `/api/v1/cae/campaigns/{campaign_id}` | Load one full campaign report and checkpoint timeline |
| `POST` | `/api/v1/cae/campaigns/{campaign_id}/resume-preview` | Diagnose checkpoint compatibility without exposing a trusted successor payload |
| `POST` | `/api/v1/cae/campaigns/{campaign_id}/resume` | Atomically validate and enqueue a checkpoint successor with lineage metadata |
| `GET` | `/api/v1/cae/resume-attempts` | List durable resume dispatches with parent, checkpoint, successor, and completion state |
| `POST` | `/api/v1/cae/resume-attempts/reconcile` | Repair missing terminal events from RQ state and mark stale missing jobs as orphaned failures |
| `GET` | `/api/v1/cae/resume-watchdog` | Read the latest immutable server-scheduled reconciliation report |
| `GET` | `/api/v1/cae/observability` | Read the React-facing durable watchdog, heartbeat, retry, and orphan-repair health snapshot |
| `GET` | `/metrics` | Scrape low-cardinality Prometheus metrics derived from durable CAE recovery artifacts |
| `POST` | `/api/v1/cae/resume-attempts/{resume_attempt_id}/retry` | Retry one terminal failed attempt with preserved checkpoint settings and new lineage |
| `GET` | `/api/v1/cae/mesh-studies` | List newest-first mesh-independence study summaries |
| `GET` | `/api/v1/cae/mesh-studies/{mesh_study_id}` | Load one full mesh-independence report |
| `GET` | `/api/v1/cae/{case_id}/artifacts/{filename}` | Download the case ZIP or solver log |
| `GET` | `/api/v1/cae/runtime-requirements` | Read the pinned CAE distribution, architecture, tutorial, and queue contract |

## Phase 1 behavior

- LHS honors the requested run count; the standards-based 5-factor CCD and BBD matrices contain 50 and 46 runs respectively.
- Model selection uses shuffled cross-validation RMSE plus holdout R², RMSE, and MAE. Training R² is never the selection criterion.
- The GPR model exposes predictive uncertainty for digital-twin what-if queries.
- Artifacts are written under `backend/data/` by default. Set `THERMOFORM_ARTIFACT_DIR` to relocate them.
- Optimization enforces `Tmax < 80°C` and pressure-drop limits against the persisted surrogate bundle.

## Phase 2 behavior

- EI, PI, and UCB use the persisted Gaussian Process mean and uncertainty to select the next experiment.
- Each selected design is evaluated by the reduced-order physics simulator, appended to a new immutable dataset, and used to update GPR before the next iteration.
- At loop completion, all four surrogate families are cross-validated again and saved as a new model artifact.
- The best feasible design is converted to a parameterized FreeCAD Python script. If FreeCAD is installed, the adapter executes it and exports STEP, STL, and FCStd; otherwise only the script and a clearly labeled fallback STL are produced.

## Async jobs and OpenFOAM handoff

- The React workflow uses `POST /jobs` and polls `GET /jobs/{id}`. DOE batches, surrogate training, optimization, and CAE preparation no longer occupy the browser's request lifecycle.
- CAE Operations submits `cae_campaign` without blocking the UI, displays queue progress and `cancel_requested`, and makes the safe checkpoint boundary explicit. Completed reports provide the checkpoint timeline, stop reason, latest/target time, resume ID, and checkpoint download.
- Coarse, medium, and fine campaign cards remain distinct. The React client enables `cae_mesh_study` only when every profile reports numerical convergence, and keeps the publication warning visible until the backend returns `design_result_available=true`.
- The active CAE job ID is stored locally as a reconnect hint, never as an engineering result. On reload the client polls that RQ job again; if the job record has expired, it removes the stale hint and falls back to immutable campaign reports.
- Campaign and mesh-study history endpoints skip corrupt/non-report directories, return compact newest-first indexes, validate report IDs before detail reads, and keep full checkpoint segment arrays behind detail requests.
- **Check & continue** never trusts browser state alone. FastAPI recomputes the expected case fingerprint, validates the selected solve report and checkpoint ZIP metadata, and rejects converged campaigns, missing resume IDs, mismatched cases/profiles/times, and targets that do not advance beyond the checkpoint.
- React never receives or resubmits a trusted resume payload. The atomic resume endpoint injects `resume_from_run_id`, parent campaign, and resume-attempt identity on the server, queues the successor, and returns its job snapshot for the existing persisted reconnect loop.
- Resume lineage is available immediately in RQ job metadata and is carried into the immutable successor campaign report, linking the parent campaign, checkpoint solve run, and deterministic resume attempt.
- Identical resume attempts share one deterministic RQ job ID under a Redis lock. Repeated requests return the existing job with `deduplicated=true`; if the job has expired but its successor report exists, the API returns that completed immutable result instead of queueing another solver run.
- Every accepted resume writes one immutable `resume-dispatch.json`. The resume-attempt history API augments those records from successor campaign reports, and CAE Operations renders the full lineage across browser sessions.
- Resume workers append one immutable artifact for every reached lifecycle state. The history endpoint exposes those events in lifecycle order and advertises `retry_allowed` only after a terminal failure.
- Retrying a failed attempt reconstructs the server-stored request, revalidates the original checkpoint, and issues `retry_of_attempt_id`, root-attempt, and retry-index lineage. The retry endpoint cannot restart queued, active, completed, or cancelled attempts.
- CAE Operations reconciles nonterminal durable attempts before each history restore. RQ `finished`, `failed`, and cancelled snapshots repair missing terminal events; live queue states are never rewritten, while missing jobs must exceed both the configured grace floor and their total-runtime + final-segment + safety-buffer window before becoming retryable orphaned failures.
- Each resumed worker atomically replaces `resume-heartbeat.json` from a dedicated heartbeat thread, so a long solver segment remains distinguishable from a dead worker even if its RQ job record disappears. Terminal events remain append-only and authoritative.
- `rq cron app.cron_config` schedules `run_resume_watchdog` on the general `thermoform` queue. Every run writes one immutable `resume-watchdog-report.json`; CAE Operations displays the latest scheduled audit separately from its on-open reconciliation.
- FastAPI derives `/metrics` and `/api/v1/cae/observability` from the shared artifact volume rather than process-local counters. Prometheus alert rules cover API availability, watchdog presence/age, heartbeat leases, orphan repair increments, and failed retries; React shows the same snapshot without parsing Prometheus text.
- Alertmanager groups by service, component, and severity; critical alerts repeat hourly, warnings repeat every four hours, API loss inhibits dependent recovery symptoms, and a missing watchdog inhibits its stale-age symptom. External delivery credentials belong only in runtime secret files.
- The recovery SLI is one only when FastAPI is scrapeable and its durable recovery-health contract is healthy. Recording rules expose thirty-day availability and remaining budget for the 99.5% objective; paired 5m/1h and 30m/6h windows alert on fast and persistent budget burn without relying on training or process-local data.
- `scripts/run_observability_alert_drill.py` starts two Prometheus replicas, a three-ingester Receive ring, Store Gateway/Query, two Alertmanagers, and an authenticated receiver. It verifies six replicated copies collapse to one logical series, then proves continuity after Receive-1, Prometheus-1, and Alertmanager-1 stop in sequence.
- The runtime Alertmanager renderer replaces all default, critical, and warning webhook endpoints only after validating HTTPS and the external token file. Alertmanager reads the token directly from `/run/secrets`; the generated YAML never contains its value.
- Prometheus scrapes both Alertmanager replicas. One reachable replica triggers a degraded warning, zero triggers the critical outage, incomplete gossip membership is detected independently, and webhook failures use a local fallback receiver.
- The isolated drill now continues through an authenticated receiver fixture, verifies the standard Alertmanager v4 payload, production severity route, bearer header, group key, and runbook annotation, and exposes no received credential in its verification API.
- Prometheus self-scraping exposes the configured retention limit and total blocks/WAL/head usage. A recording rule alerts at 80% so operators can preserve the recommended host-disk compaction buffer instead of treating the retention limit as usable disk capacity.
- `observability_state.py` resolves eight source-of-truth observability volumes through exact Compose labels, refuses active or nonempty volumes, produces checksummed archives, rejects hostile tar members, and retains schema 1–3 restore compatibility. Store Gateway cache is deliberately rebuildable and excluded.
- `run_observability_state_drill.py` uploads a deterministic historical block, proves Store Gateway still serves it after all Receive ingesters stop, restores eight archives after volume reconstruction, and verifies the block plus replicated Alertmanager silence and real-time data.
- Prometheus replicas use stable `cluster`/`replica` labels; Receive ingesters add `receive_replica`. Query removes both dimensions for normal views. The filesystem bucket and all processes share one host, so production object-store and host-level HA are not claimed.
- `render_thanos_s3_config.py` emits a credential-free S3 configuration for SDK workload identity, TLS, signature v4, content MD5, and SSE-S3/SSE-KMS. `THERMOFORM_THANOS_OBJECT_STORE_CONFIG` mounts that one file into every object-store client; it does not provision or migrate the bucket.
- Phase 1 and Phase 2 use `thermoform`; `cae`, `cae_mesh`, `cae_smoke`, `cae_solve`, `cae_campaign`, `cae_mesh_study`, and `cae_benchmark` are isolated on `thermoform-cae`, so a general worker cannot accidentally claim an OpenFOAM task.
- API and worker containers share `/data`, so immutable datasets, model bundles, CAD files, and CAE packages remain available after a job completes.
- The OpenFOAM ZIP includes the watertight fused parametric STL, case manifest, enclosing `blockMesh`, explicit `fluid`/`solid` snappyHexMesh seeds, region-splitting setup, fields/materials, response function objects, and a fail-fast preprocessing `Allrun`. Its bundled `Allsolve` remains a one-step smoke command; production execution is owned by `cae_solve`.
- Generated cases are marked `case_validated=false`, `results_available=false`, and `not_cfd_result=true`. Installing OpenFOAM alone does not turn a starter case into a validated CAE result.
- `cae_mesh` executes the package on the OpenFOAM worker and persists immutable `mesh.log` and `mesh-report.json` artifacts. Passing means the configured preprocessing gates passed; `results_available` remains false because no thermal solution exists yet.
- `cae_smoke` first enforces the same mesh gates, then requires both thermo regions, the configured `heatSource`, coupled energy, momentum/pressure fields, clean solver termination, and persisted `smoke.log`/`smoke-report.json` artifacts. A pass validates startup compatibility only; extracted diagnostics remain provisional and are never published as CFD responses.
- Response probes run as OpenFOAM function objects at write time. The one-step integration test produced 25°C, 0 Pa pressure drop, and 0.0001455 W heat-out with 99.99985% energy imbalance; these intentionally remain provisional and unavailable as engineering results.
- `cae_solve` restores the latest regional fields from an immutable ZIP, validates the checkpoint case fingerprint, and writes a successor checkpoint after completion, timeout, or recoverable solver failure. Temporary expanded cases are retained only if a worker is interrupted before it can write a report.
- `cae_campaign` repeatedly advances the latest checkpoint and stops on numerical convergence, a cooperative cancel request, target time, segment limit, runtime budget, missing checkpoint, failed segment, or lack of time progress. Every stop reason is persisted in an immutable campaign report.
- A queued job can be cancelled immediately. A running campaign records `cancel_requested` in RQ metadata and checks it between segments, so the current OpenFOAM process can finish writing a recoverable checkpoint before the campaign stops.
- Coarse, medium, and fine meshes use distinct fingerprints and systematically scale all background cell counts by 0.8, 1.0, and 1.25. A converged campaign is a numerical candidate only; it reports `design_result_available=false` until `cae_mesh_study` validates all three profiles.
- `cae_mesh_study` requires the same design/boundary fingerprint across the three converged campaigns. It compares coarse-to-medium and medium-to-fine responses, and publishes the fine result only when the decisive medium-to-fine Tmax and pressure-drop changes pass their limits.
- For parallel CHT, `topoSet` creates matching interface face sets in both regions and `singleProcessorFaceSets` keeps the implicit coupled faces on processor 0 before `decomposePar -allRegions`. The worker runs `chtMultiRegionFoam -parallel` through MPI and reconstructs the exact latest processor time.
- The real two-process validation resumed a 1,975,393-cell design from `1e-5 s` to `2e-5 s`, reconstructed both regions, and generated a valid successor checkpoint. Residuals passed (`3.18e-6` maximum final residual), but only 2 of 5 samples were available and energy imbalance remained 99.99985%, so the run correctly returned `completed_unconverged` with `results_available=false`.
- Heat-sink solver execution is blocked while union geometry, interfaces, fields, material properties, mesh quality, convergence, or energy balance remain unvalidated.
- The benchmark worker targets the official OpenCFD OpenFOAM v2312 `multiRegionHeater` tutorial. Start the worker from a sourced OpenFOAM shell and expose either `FOAM_TUTORIALS` or `THERMOFORM_OPENFOAM_BENCHMARK_CASE`.
- A tutorial benchmark passes only after successful execution, `Mesh OK`, mesh limits, an `End` marker, and converged final residuals. It still returns `results_available=false` because it is not the optimized heat-sink geometry.
- A design result additionally requires standardized `THERMOFORM_METRIC` values for `t_max_c`, `pressure_drop_pa`, `heat_in_w`, and `heat_out_w`; the energy imbalance must remain within the configured limit.
- `Dockerfile.openfoam` pins the official `2312.260127-2` runtime/common/tutorial packages and verifies all three repository SHA-256 values before installation. The image uses `linux/amd64`, matching the published OpenCFD Debian binaries; Apple Silicon Docker uses emulation for this worker.
- The CAE worker entrypoint sources the packaged OpenFOAM environment, verifies `WM_PROJECT_VERSION` (with `/usr/bin/openfoam2312 -show-api` as fallback), checks the official tutorial directory, exports its resolved location, and exits before starting RQ if any capability is absent.
- The Compose CAE profile has been exercised end-to-end with the packaged v2312 `multiRegionHeater` tutorial: RQ completed the solver, `checkMesh -allRegions` passed, and convergence passed while result availability correctly remained false for this non-design benchmark.

## Verification

```bash
cd backend && .venv/bin/pytest
cd frontend && npm test && npm run build
```

The frontend retains a read-only preview if the API is unavailable. Clicking **Run workflow** while FastAPI is connected replaces the demo values across DOE, simulation, analysis, surrogate, optimization, and digital-twin views with one traceable Phase 1 result.
