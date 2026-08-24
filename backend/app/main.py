import os
import json
import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from app.api.routes import router
from app.api.phase1 import router as phase1_router
from app.api.phase2 import router as phase2_router
from app.api.jobs import router as jobs_router, ws_router
from app.api.cae import router as cae_router
from app.api.metrics import router as metrics_router
from app.api.projects import router as projects_router
from app.api.agent import router as agent_router
from app.db.session import init_db
from app.core.logging import configure_logging


configure_logging()
request_logger = logging.getLogger("thermoform.http")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.getenv("THERMOFORM_AUTO_CREATE_SCHEMA", "true").lower() == "true":
        init_db()
    yield


app = FastAPI(
    title="Thermoform Engineering API",
    description="DOE and reduced-order thermal simulation API. Results are not CFD.",
    version="1.0.0",
    lifespan=lifespan,
)
cors_origins = os.getenv("THERMOFORM_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in cors_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RedisError)
async def redis_unavailable(_: Request, __: RedisError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Job queue is unavailable"})


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID", f"req_{uuid4().hex}")
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    content_type = response.headers.get("content-type", "")
    if request.url.path.startswith("/api/v1") and "application/json" in content_type:
        body = b"".join([chunk async for chunk in response.body_iterator])
        payload = json.loads(body or b"null")
        if isinstance(payload, dict) and "meta" not in payload:
            payload["meta"] = {
                "request_id": request.state.request_id,
                "project_id": payload.get("project_id"),
                "job_id": payload.get("job_id"),
                "model_id": payload.get("model_id"),
                "dataset_version": payload.get("dataset_version"),
                "status": "success" if response.status_code < 400 else "error",
            }
            payload["error"] = (
                None
                if response.status_code < 400
                else {"detail": payload.get("detail", "Request failed")}
            )
        headers = dict(response.headers)
        headers.pop("content-length", None)
        response = Response(
            content=json.dumps(payload, default=str),
            status_code=response.status_code,
            headers=headers,
            media_type="application/json",
            background=response.background,
        )
        response.headers["X-Request-ID"] = request.state.request_id
    request_logger.info(
        "request_completed",
        extra={
            "request_id": request.state.request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        },
    )
    return response


app.include_router(router)
app.include_router(phase1_router)
app.include_router(phase2_router)
app.include_router(jobs_router)
app.include_router(ws_router)
app.include_router(cae_router)
app.include_router(metrics_router)
app.include_router(projects_router)
app.include_router(agent_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "Thermoform Engineering API", "docs": "/docs"}
