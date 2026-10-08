import json
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # slug = name
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # optimistic lock (RESIL-04)

    # lazy="selectin" is required for async — default lazy triggers MissingGreenlet
    steps: Mapped[list["WorkflowStep"]] = relationship(
        "WorkflowStep",
        order_by="WorkflowStep.step_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (UniqueConstraint("workflow_def_id", "step_order"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)  # UUID string
    workflow_def_id: Mapped[str] = mapped_column(
        String, ForeignKey("workflow_definitions.id", ondelete="CASCADE"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    execute_url: Mapped[str] = mapped_column(Text, nullable=False)
    compensate_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    retry_policy: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON blob; enforcement deferred to v2
