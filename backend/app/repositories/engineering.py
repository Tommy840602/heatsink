from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.tables import (
    DesignRecord,
    ExperimentRecord,
    ModelRecord,
    OptimizationRecord,
    ProjectRecord,
    SimulationRecord,
)
from app.domain.projects import DesignCreate, ProjectCreate, ProjectUpdate


class EngineeringRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_project(self, payload: ProjectCreate) -> ProjectRecord:
        record = ProjectRecord(**payload.model_dump())
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_projects(self) -> list[ProjectRecord]:
        return list(self.session.scalars(select(ProjectRecord).order_by(ProjectRecord.created_at.desc())))

    def get_project(self, project_id: str) -> ProjectRecord | None:
        return self.session.get(ProjectRecord, project_id)

    def update_project(self, project: ProjectRecord, payload: ProjectUpdate) -> ProjectRecord:
        for key, value in payload.model_dump(exclude_none=True).items():
            setattr(project, key, value)
        self.session.commit()
        self.session.refresh(project)
        return project

    def create_design(self, project_id: str, payload: DesignCreate) -> DesignRecord:
        latest = self.session.scalar(
            select(func.max(DesignRecord.version)).where(
                DesignRecord.project_id == project_id,
                DesignRecord.name == payload.name,
            )
        )
        record = DesignRecord(
            project_id=project_id,
            name=payload.name,
            version=int(latest or 0) + 1,
            parameters=payload.parameters.model_dump(),
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_designs(self, project_id: str) -> list[DesignRecord]:
        return list(
            self.session.scalars(
                select(DesignRecord)
                .where(DesignRecord.project_id == project_id)
                .order_by(DesignRecord.created_at.desc())
            )
        )

    def get_design(self, design_id: str) -> DesignRecord | None:
        return self.session.get(DesignRecord, design_id)

    def list_experiments(self, project_id: str) -> list[ExperimentRecord]:
        return list(self.session.scalars(select(ExperimentRecord).where(ExperimentRecord.project_id == project_id).order_by(ExperimentRecord.created_at.desc())))

    def list_simulations(self, project_id: str) -> list[SimulationRecord]:
        return list(self.session.scalars(select(SimulationRecord).where(SimulationRecord.project_id == project_id).order_by(SimulationRecord.created_at.desc())))

    def list_models(self, project_id: str) -> list[ModelRecord]:
        return list(self.session.scalars(select(ModelRecord).where(ModelRecord.project_id == project_id).order_by(ModelRecord.created_at.desc())))

    def list_optimizations(self, project_id: str) -> list[OptimizationRecord]:
        return list(self.session.scalars(select(OptimizationRecord).where(OptimizationRecord.project_id == project_id).order_by(OptimizationRecord.created_at.desc())))

    def get_optimization(self, optimization_id: str) -> OptimizationRecord | None:
        return self.session.get(OptimizationRecord, optimization_id)
