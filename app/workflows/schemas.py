import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, HttpUrl, field_validator


class RetryPolicySchema(BaseModel):
    max_attempts: int = 3
    backoff_seconds: float = 1.0
    max_delay_seconds: float = 30.0


class StepCreateSchema(BaseModel):
    name: str
    execute_url: HttpUrl
    compensate_url: HttpUrl | None = None
    timeout_seconds: int = 30
    retry_policy: RetryPolicySchema | None = None


class WorkflowCreateRequest(BaseModel):
    name: str
    description: str | None = None
    steps: list[StepCreateSchema]

    @field_validator("steps")
    @classmethod
    def steps_not_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("steps must not be empty")
        return v


class StepResponse(BaseModel):
    id: str
    step_order: int
    name: str
    execute_url: str
    compensate_url: str | None
    timeout_seconds: int
    retry_policy: dict | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def model_validate(cls, obj: Any, **kwargs) -> "StepResponse":
        instance = super().model_validate(obj, **kwargs)
        # Deserialize JSON blob stored in retry_policy column
        if isinstance(getattr(obj, "retry_policy", None), str):
            instance.retry_policy = json.loads(obj.retry_policy)
        return instance


class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: str | None
    steps: list[StepResponse]
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def model_validate(cls, obj: Any, **kwargs) -> "WorkflowResponse":
        instance = super().model_validate(obj, **kwargs)
        instance.steps = [StepResponse.model_validate(s) for s in obj.steps]
        return instance
