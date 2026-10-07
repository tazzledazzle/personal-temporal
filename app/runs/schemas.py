"""
Pydantic v2 schemas for workflow run endpoints.

StartRunRequest  — POST /workflows/{name}/runs request body
RunResponse      — GET /runs/{run_id} response
StepExecutionResponse — GET /runs/{run_id}/steps item response
"""

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator


class StartRunRequest(BaseModel):
    input: dict | None = None


class StepExecutionResponse(BaseModel):
    id: str
    step_index: int
    step_name: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    http_status_code: int | None
    error_detail: str | None
    compensation_status: str | None
    compensated_at: datetime | None
    compensation_error: str | None
    model_config = {"from_attributes": True}


class RunResponse(BaseModel):
    id: str
    workflow_def_id: str
    status: str
    current_step_index: int
    input_payload: dict | str | None
    started_at: datetime | None
    completed_at: datetime | None
    error_detail: str | None
    model_config = {"from_attributes": True}

    @field_validator("input_payload", mode="before")
    @classmethod
    def parse_input_payload(cls, v: Any) -> dict | None:
        if isinstance(v, str):
            return json.loads(v)
        return v
