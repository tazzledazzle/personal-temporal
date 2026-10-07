"""
WorkflowRun stub model.

Schema only — populated in Phase 2 when the execution engine is built.
Created in Phase 1 so the DEFN-03 active-run guard query (DELETE /workflows/{name})
compiles and returns 0 rows rather than failing with a missing table error.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WorkflowRun(Base):
    """Persisted state for a single workflow run instance."""

    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # UUID string
    workflow_def_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
