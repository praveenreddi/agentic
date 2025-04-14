from typing import Optional
from pydantic import BaseModel


class NotifyConfig(BaseModel):
    """Model for job notification configuration."""

    enabled: bool = True
    method: Optional[str] = None  # email, webhook
    email: Optional[str] = None
    webhook: Optional[str] = None
