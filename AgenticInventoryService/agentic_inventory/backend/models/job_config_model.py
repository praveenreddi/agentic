import yaml
from pathlib import Path

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, ConfigDict
from agentic_inventory.backend.models.notify_config_model import NotifyConfig


class JobConfig(BaseModel):
    """Model for job configuration stored in YAML."""

    id: str = Field(default_factory=lambda: f"job_{datetime.now(timezone.utc).timestamp()}")
    job_name: str
    description: Optional[str] = None
    schedule: str  # Cron expression or predefined schedule
    parameters: Dict[str, Any] = Field(default_factory=dict)
    output_location: Optional[str] = None
    notify: Optional[NotifyConfig] = None
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tags: List[str] = Field(default_factory=list)
    enabled: bool = True
    timeout: Optional[int] = None  # Timeout in seconds
    retry_count: int = 3
    retry_delay: int = 60  # Delay between retries in seconds
    jitter: Optional[int] = Field(
        default=None,
        description="Random jitter in seconds to prevent  jobs from starting at exactly the same time.",
    )

    model_config = ConfigDict(populate_by_name=True, json_encoders={datetime: lambda v: v.isoformat() if v else None})

    def model_dump(self, **kwargs):
        """Override model_dump to handle datetime serialization."""
        data = super().model_dump(**kwargs)
        for field in ["created_at", "updated_at"]:
            if field in data and data[field]:
                data[field] = data[field].isoformat()
        return data

    def to_yaml(self, file_path: str) -> None:
        """Save configuration to YAML file."""

        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False)

    @classmethod
    def from_yaml(cls, file_path: str) -> "JobConfig":
        """Load configuration from YAML file."""

        with open(file_path, "r") as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def update(self, **kwargs) -> None:
        """Update configuration fields and timestamp."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.updated_at = datetime.now(timezone.utc)
