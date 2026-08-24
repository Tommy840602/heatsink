#!/usr/bin/env python3
"""Create the reproducible interview-demo project and Phase 1 artifacts."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select

from app.db.session import SessionLocal, init_db
from app.db.tables import ProjectRecord
from app.domain.models import DesignParameters
from app.domain.phase1 import Phase1WorkflowRequest
from app.domain.projects import DesignCreate, ProjectCreate
from app.repositories.engineering import EngineeringRepository
from app.services.workflow import run_phase1


def main() -> None:
    init_db()
    with SessionLocal() as session:
        repository = EngineeringRepository(session)
        project = session.scalar(select(ProjectRecord).where(ProjectRecord.name == "Thermoform Demo (seed 42)"))
        if project is None:
            project = repository.create_project(ProjectCreate(name="Thermoform Demo (seed 42)", description="Reproducible engineering demo data"))
            repository.create_design(
                project.id,
                DesignCreate(
                    name="Baseline",
                    parameters=DesignParameters(fin_count=40, fin_thickness=0.6, fin_height=40, fin_spacing=2.0, air_velocity=2.0),
                ),
            )
        project_id = project.id
    result = run_phase1(Phase1WorkflowRequest(project_id=project_id, method="LHS", runs=48, seed=42))
    print(json.dumps({"project_id": project_id, "workflow_id": result["workflow_id"], "dataset_version": result["dataset_version"], "model_id": result["model_id"]}))


if __name__ == "__main__":
    main()
