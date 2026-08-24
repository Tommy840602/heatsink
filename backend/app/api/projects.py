from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.projects import (
    ApiEnvelope,
    ApiMeta,
    DesignCreate,
    DesignCreateForProject,
    DesignView,
    ProjectCreate,
    ProjectUpdate,
    ProjectView,
)
from app.repositories.engineering import EngineeringRepository


router = APIRouter(prefix="/api/v1", tags=["projects"])


def envelope(request: Request, data, *, project_id: str | None = None, status_name: str = "success"):
    return ApiEnvelope(
        data=data,
        meta=ApiMeta(
            request_id=getattr(request.state, "request_id", f"req_{uuid4().hex}"),
            project_id=project_id,
            status=status_name,
        ),
    )


def require_project(repository: EngineeringRepository, project_id: str):
    project = repository.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/projects", response_model=ApiEnvelope, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, request: Request, db: Session = Depends(get_db)):
    project = EngineeringRepository(db).create_project(payload)
    return envelope(request, ProjectView.model_validate(project).model_dump(), project_id=project.id)


@router.get("/projects", response_model=ApiEnvelope)
def list_projects(request: Request, db: Session = Depends(get_db)):
    projects = EngineeringRepository(db).list_projects()
    return envelope(request, [ProjectView.model_validate(row).model_dump() for row in projects])


@router.get("/projects/{project_id}", response_model=ApiEnvelope)
def get_project(project_id: str, request: Request, db: Session = Depends(get_db)):
    project = require_project(EngineeringRepository(db), project_id)
    return envelope(request, ProjectView.model_validate(project).model_dump(), project_id=project.id)


@router.patch("/projects/{project_id}", response_model=ApiEnvelope)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    repository = EngineeringRepository(db)
    project = repository.update_project(require_project(repository, project_id), payload)
    return envelope(request, ProjectView.model_validate(project).model_dump(), project_id=project.id)


@router.delete("/projects/{project_id}", response_model=ApiEnvelope)
def archive_project(project_id: str, request: Request, db: Session = Depends(get_db)):
    repository = EngineeringRepository(db)
    project = repository.update_project(
        require_project(repository, project_id), ProjectUpdate(status="archived")
    )
    return envelope(
        request,
        ProjectView.model_validate(project).model_dump(),
        project_id=project.id,
        status_name="archived",
    )


@router.post(
    "/projects/{project_id}/designs",
    response_model=ApiEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def create_design(
    project_id: str,
    payload: DesignCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    repository = EngineeringRepository(db)
    require_project(repository, project_id)
    design = repository.create_design(project_id, payload)
    return envelope(request, DesignView.model_validate(design).model_dump(), project_id=project_id)


@router.get("/projects/{project_id}/designs", response_model=ApiEnvelope)
def list_designs(project_id: str, request: Request, db: Session = Depends(get_db)):
    repository = EngineeringRepository(db)
    require_project(repository, project_id)
    designs = repository.list_designs(project_id)
    return envelope(
        request,
        [DesignView.model_validate(row).model_dump() for row in designs],
        project_id=project_id,
    )


@router.get("/designs/{design_id}", response_model=ApiEnvelope)
def get_design(design_id: str, request: Request, db: Session = Depends(get_db)):
    design = EngineeringRepository(db).get_design(design_id)
    if design is None:
        raise HTTPException(status_code=404, detail="Design not found")
    return envelope(request, DesignView.model_validate(design).model_dump(), project_id=design.project_id)


@router.post("/designs", response_model=ApiEnvelope, status_code=status.HTTP_201_CREATED)
def create_design_alias(
    payload: DesignCreateForProject,
    request: Request,
    db: Session = Depends(get_db),
):
    repository = EngineeringRepository(db)
    require_project(repository, payload.project_id)
    design = repository.create_design(
        payload.project_id,
        DesignCreate(name=payload.name, parameters=payload.parameters),
    )
    return envelope(
        request,
        DesignView.model_validate(design).model_dump(),
        project_id=payload.project_id,
    )


def _record_dict(record):
    return {
        attribute.columns[0].name: getattr(record, attribute.key)
        for attribute in record.__mapper__.column_attrs
    }


@router.get("/projects/{project_id}/experiments", response_model=ApiEnvelope)
def list_experiments(project_id: str, request: Request, db: Session = Depends(get_db)):
    repository = EngineeringRepository(db)
    require_project(repository, project_id)
    return envelope(request, [_record_dict(row) for row in repository.list_experiments(project_id)], project_id=project_id)


@router.get("/projects/{project_id}/simulations", response_model=ApiEnvelope)
def list_simulations(project_id: str, request: Request, db: Session = Depends(get_db)):
    repository = EngineeringRepository(db)
    require_project(repository, project_id)
    return envelope(request, [_record_dict(row) for row in repository.list_simulations(project_id)], project_id=project_id)


@router.get("/projects/{project_id}/models", response_model=ApiEnvelope)
def list_models(project_id: str, request: Request, db: Session = Depends(get_db)):
    repository = EngineeringRepository(db)
    require_project(repository, project_id)
    return envelope(request, [_record_dict(row) for row in repository.list_models(project_id)], project_id=project_id)


@router.get("/projects/{project_id}/optimizations", response_model=ApiEnvelope)
def list_optimizations(project_id: str, request: Request, db: Session = Depends(get_db)):
    repository = EngineeringRepository(db)
    require_project(repository, project_id)
    return envelope(request, [_record_dict(row) for row in repository.list_optimizations(project_id)], project_id=project_id)


@router.get("/optimizations/{optimization_id}/pareto-front", response_model=ApiEnvelope)
def get_pareto_front(optimization_id: str, request: Request, db: Session = Depends(get_db)):
    optimization = EngineeringRepository(db).get_optimization(optimization_id)
    if optimization is None:
        raise HTTPException(status_code=404, detail="Optimization not found")
    return envelope(
        request,
        {
            "optimization_id": optimization.id,
            "objectives": optimization.objectives,
            "pareto": optimization.result.get("pareto", []),
            "recommended": optimization.result.get("recommended"),
        },
        project_id=optimization.project_id,
    )
