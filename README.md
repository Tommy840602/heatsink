# Thermoform — AI-Assisted Thermal Design Platform

Thermoform is a separated React + FastAPI engineering application for heat-sink design exploration. Phase 1 is an executable DOE → physics simulation → statistical analysis → surrogate training → optimization loop, with immutable dataset/model artifacts and a React digital-twin interface.

> The built-in physics simulator is a reduced-order engineering model, not CFD or CAE.

## Architecture

```text
Browser
  └─ React frontend (:3000)
       └─ typed HTTP client
            └─ FastAPI backend (:8000)
                 ├─ design validation + standard CCD / BBD / LHS
                 ├─ deterministic thermal, pressure-drop, and mass simulation
                 ├─ quadratic RSM, ANOVA, and residual diagnostics
                 ├─ RSM / Random Forest / XGBoost / GPR evaluation
                 ├─ differential evolution + NSGA-II optimization
                 └─ versioned dataset and model artifacts
```

```text
frontend/   React 19, TypeScript, Vinext/Vite, responsive engineering UI
backend/    FastAPI, Pydantic, pyDOE3, SciPy, scikit-learn, XGBoost, pymoo
```

## One-command startup

```bash
docker compose up --build
```

- Frontend: http://localhost:3000
- FastAPI docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/v1/health

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

## Phase 1 behavior

- LHS honors the requested run count; the standards-based 5-factor CCD and BBD matrices contain 50 and 46 runs respectively.
- Model selection uses shuffled cross-validation RMSE plus holdout R², RMSE, and MAE. Training R² is never the selection criterion.
- The GPR model exposes predictive uncertainty for digital-twin what-if queries.
- Artifacts are written under `backend/data/` by default. Set `THERMOFORM_ARTIFACT_DIR` to relocate them.
- Optimization enforces `Tmax < 80°C` and pressure-drop limits against the persisted surrogate bundle.

## Verification

```bash
cd backend && .venv/bin/pytest
cd frontend && npm run build
```

The frontend retains a read-only preview if the API is unavailable. Clicking **Run workflow** while FastAPI is connected replaces the demo values across DOE, simulation, analysis, surrogate, optimization, and digital-twin views with one traceable Phase 1 result.
