from fastapi import APIRouter, Response

from app.repositories.artifacts import ArtifactRepository
from app.services.cae_observability import (
    PROMETHEUS_CONTENT_TYPE,
    build_cae_observability_snapshot,
    render_prometheus_metrics,
)


router = APIRouter()
repository = ArtifactRepository()


@router.get("/api/v1/cae/observability")
def cae_observability() -> dict:
    return build_cae_observability_snapshot(repository)


@router.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    snapshot = build_cae_observability_snapshot(repository)
    return Response(
        content=render_prometheus_metrics(snapshot),
        headers={"content-type": PROMETHEUS_CONTENT_TYPE},
    )
