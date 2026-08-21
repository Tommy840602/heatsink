# Thermoform — AI-Assisted Thermal Design Platform

Thermoform is a separated React + FastAPI engineering application for heat-sink design exploration. The frontend visualizes the complete DOE → simulation → surrogate → optimization workflow. The backend owns parameter validation, experiment generation, and the deterministic reduced-order thermal model.

> The built-in physics simulator is a reduced-order engineering model, not CFD or CAE.

## Architecture

```text
Browser
  └─ React frontend (:3000)
       └─ typed HTTP client
            └─ FastAPI backend (:8000)
                 ├─ design validation
                 ├─ CCD / BBD / LHS generation
                 └─ thermal, pressure-drop, and mass simulation
```

```text
frontend/   React 19, TypeScript, Vinext/Vite, responsive engineering UI
backend/    FastAPI, Pydantic domain schemas, DOE and simulator services
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

## Verification

```bash
cd backend && .venv/bin/pytest
cd frontend && npm run build
```

The frontend retains a read-only preview estimate if the API is unavailable, while all validation, DOE generation, and authoritative live predictions are requested from FastAPI.
