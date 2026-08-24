"""add simulation run metadata

Revision ID: 20260824_02
Revises: 20260824_01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260824_02"
down_revision: str | None = "20260824_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "simulation_runs",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=True),
        sa.Column("dataset_version", sa.String(length=80), nullable=False),
        sa.Column("simulator_version", sa.String(length=40), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("noise_std", sa.Float(), nullable=False),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("result_kind", sa.String(length=32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_simulation_runs_project_id", "simulation_runs", ["project_id"])
    op.create_index("ix_simulation_runs_dataset_version", "simulation_runs", ["dataset_version"])


def downgrade() -> None:
    op.drop_index("ix_simulation_runs_dataset_version", table_name="simulation_runs")
    op.drop_index("ix_simulation_runs_project_id", table_name="simulation_runs")
    op.drop_table("simulation_runs")
