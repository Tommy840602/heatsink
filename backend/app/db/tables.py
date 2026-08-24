from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def identifier(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class ProjectRecord(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: identifier("project"))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    design_space: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    designs: Mapped[list["DesignRecord"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class DesignRecord(Base):
    __tablename__ = "designs"
    __table_args__ = (UniqueConstraint("project_id", "name", "version", name="uq_design_version"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: identifier("design"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), default="Heat sink design")
    version: Mapped[int] = mapped_column(Integer, default=1)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    project: Mapped[ProjectRecord] = relationship(back_populates="designs")


class ExperimentRecord(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: identifier("experiment"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    dataset_version: Mapped[str] = mapped_column(String(80), index=True)
    method: Mapped[str] = mapped_column(String(32))
    seed: Mapped[int] = mapped_column(Integer)
    run_count: Mapped[int] = mapped_column(Integer)
    noise_std: Mapped[float] = mapped_column(Float, default=0.0)
    simulator_version: Mapped[str] = mapped_column(String(40))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SimulationRecord(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: identifier("simulation"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    dataset_version: Mapped[str] = mapped_column(String(80), index=True)
    simulator_version: Mapped[str] = mapped_column(String(40))
    seed: Mapped[int] = mapped_column(Integer)
    noise_std: Mapped[float] = mapped_column(Float, default=0.0)
    run_count: Mapped[int] = mapped_column(Integer)
    result_kind: Mapped[str] = mapped_column(String(32), default="physics_model")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelRecord(Base):
    __tablename__ = "models"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    dataset_version: Mapped[str] = mapped_column(String(80), index=True)
    artifact_path: Mapped[str] = mapped_column(Text)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    hyperparameters: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OptimizationRecord(Base):
    __tablename__ = "optimization_runs"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    model_id: Mapped[str] = mapped_column(String(80), index=True)
    objectives: Mapped[list] = mapped_column(JSON)
    constraints: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
