from datetime import datetime
from uuid import uuid4
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from marshmallow import Schema, fields, EXCLUDE
from agentic_inventory.backend.models.system_metadata_model import SystemMetadataSchema


class JobExecutionModel(BaseModel):
    """Model for job execution records."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    job_name: str
    status: str
    result: Optional[Dict[str, Any]] = None
    createdAt: datetime = Field(default_factory=datetime.now)
    updatedAt: datetime = Field(default_factory=datetime.now)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    config: Optional[Dict[str, Any]] = None

    def __init__(self, **data):
        super().__init__(**data)
        if not self.updatedAt:
            self.updatedAt = self.createdAt

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}

    def to_json(self):
        return JobExecutionSchema().dump(self)

    @classmethod
    def from_json(cls, job_execution_json):
        schema = JobExecutionSchema()
        data = schema.load(job_execution_json)
        return cls(**data)


class JobExecutionSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    id = fields.Str(dump_default=str(uuid4()))
    job_name = fields.Str(required=True)
    status = fields.Str(required=True)
    result = fields.Dict(required=False, allow_none=True)
    createdAt = fields.DateTime(required=True)
    updatedAt = fields.DateTime(required=True)
    start_time = fields.DateTime(required=False, allow_none=True)
    end_time = fields.DateTime(required=False, allow_none=True)
    config = fields.Dict(required=False, allow_none=True)
    systemMeta = fields.Nested(SystemMetadataSchema)
