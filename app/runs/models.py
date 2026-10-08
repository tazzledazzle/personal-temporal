"""
WorkflowRun and WorkflowStepExecution ORM models.

Phase 2 replacement of the Phase 1 stub. Adds execution state, per-step
history, and Phase 3 compensation columns (nullable stubs).
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class WorkflowRun(Base):
    """Persisted state for a single workflow run instance."""

    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # UUID string
    workflow_def_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    # PENDING | RUNNING | COMPLETED | FAILED
    current_step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_payload: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON blob
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)  # retained from stub
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # lazy="selectin" required for async (default lazy triggers MissingGreenlet)
    step_executions: Mapped[list["WorkflowStepExecution"]] = relationship(
        "WorkflowStepExecution",
        order_by="WorkflowStepExecution.step_index",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class WorkflowStepExecution(Base):
    """Persisted state for a single step execution within a run."""

    __tablename__ = "workflow_step_executions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    # PENDING | RUNNING | COMPLETED | FAILED
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    http_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 3 compensation columns (nullable stubs — populated by CompensationCoordinator)
    compensation_status: Mapped[str | None] = mapped_column(String, nullable=True)
    compensated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    compensation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
