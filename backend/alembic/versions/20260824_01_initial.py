"""Initial engineering metadata schema."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260824_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_projects_status", "projects", ["status"])
    op.create_table(
        "designs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("project_id", sa.String(40), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "name", "version", name="uq_design_version"),
    )
    op.create_index("ix_designs_project_id", "designs", ["project_id"])
    op.create_table(
        "experiments",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("project_id", sa.String(40), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("dataset_version", sa.String(80), nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("noise_std", sa.Float(), nullable=False),
        sa.Column("simulator_version", sa.String(40), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_experiments_project_id", "experiments", ["project_id"])
    op.create_index("ix_experiments_dataset_version", "experiments", ["dataset_version"])
    op.create_table(
        "models",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("project_id", sa.String(40), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("dataset_version", sa.String(80), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("hyperparameters", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_models_project_id", "models", ["project_id"])
    op.create_index("ix_models_dataset_version", "models", ["dataset_version"])
    op.create_table(
        "optimization_runs",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("project_id", sa.String(40), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("model_id", sa.String(80), nullable=False),
        sa.Column("objectives", sa.JSON(), nullable=False),
        sa.Column("constraints", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_optimization_runs_project_id", "optimization_runs", ["project_id"])
    op.create_index("ix_optimization_runs_model_id", "optimization_runs", ["model_id"])


def downgrade() -> None:
    op.drop_table("optimization_runs")
    op.drop_table("models")
    op.drop_table("experiments")
    op.drop_table("designs")
    op.drop_table("projects")
