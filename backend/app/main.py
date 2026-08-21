import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.phase1 import router as phase1_router
from app.api.phase2 import router as phase2_router
from app.api.jobs import router as jobs_router
from app.api.cae import router as cae_router


app = FastAPI(
    title="Thermoform Engineering API",
    description="DOE and reduced-order thermal simulation API. Results are not CFD.",
    version="1.0.0",
)
cors_origins = os.getenv("THERMOFORM_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in cors_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(phase1_router)
app.include_router(phase2_router)
app.include_router(jobs_router)
app.include_router(cae_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "Thermoform Engineering API", "docs": "/docs"}
