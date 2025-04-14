from datetime import datetime
from typing import Dict, Optional, Any
from pydantic import BaseModel, Field
from enum import Enum
from agentic_inventory.backend.models.job_config_model import JobConfig
from agentic_inventory.backend.models.notify_config_model import NotifyConfig


class JobStatus(str, Enum):
    """Enum for job statuses."""

    QUEUED = "queued"
    EXECUTING = "executing"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Job(BaseModel):
    """Model for job execution."""

    id: str = Field(default_factory=lambda: f"job_{datetime.now().timestamp()}")
    job_name: str
    status: JobStatus = JobStatus.QUEUED
    config: JobConfig
    notify: Optional[NotifyConfig] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Contains either success data or error information"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)
