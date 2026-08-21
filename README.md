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

> The built-in physics simulator is a reduced-order engineering model, not CFD or CAE.

## Architecture

```text
Browser
  └─ React frontend (:3000)
       └─ JavaScript HTTP client
            └─ FastAPI backend (:8000)
                 ├─ Redis job queue → isolated RQ worker
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
- Redis and the RQ worker run as internal Compose services.
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
