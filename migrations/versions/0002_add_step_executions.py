"""add step executions and expand workflow runs

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("current_step_index", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("workflow_runs", sa.Column("input_payload", sa.Text(), nullable=True))
    op.add_column("workflow_runs", sa.Column("started_at", sa.DateTime(), nullable=True))
    op.add_column("workflow_runs", sa.Column("completed_at", sa.DateTime(), nullable=True))
    op.add_column("workflow_runs", sa.Column("error_detail", sa.Text(), nullable=True))

    op.create_table(
        "workflow_step_executions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("compensation_status", sa.String(), nullable=True),
        sa.Column("compensated_at", sa.DateTime(), nullable=True),
        sa.Column("compensation_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("workflow_step_executions")
    op.drop_column("workflow_runs", "error_detail")
    op.drop_column("workflow_runs", "completed_at")
    op.drop_column("workflow_runs", "started_at")
    op.drop_column("workflow_runs", "input_payload")
    op.drop_column("workflow_runs", "current_step_index")
