"""
Chat session model for the Agentic Inventory Service.

This module defines the data model for chat sessions.
"""

import datetime
from typing import Any
from uuid import uuid4
import orjson
import pytz
from marshmallow import Schema, SchemaOpts, fields, EXCLUDE

from agentic_inventory.backend.models.system_metadata_model import SystemMetadataModel, SystemMetadataSchema


class CustomOptions(SchemaOpts):
    def __init__(self, meta, ordered=True, *args, **kwargs):
        super().__init__(meta, ordered, *args, **kwargs)
        self.dateformat = "iso"
        # the whole point of this is to set a better json ser/deser
        self.render_module = orjson
        self.ordered = ordered
        self.strict = True


class ChatSessionModel:

    def __init__(
        self,
        id: str = None,
        user_id: str = None,  # Renamed from memberId for consistency
        correlation_id: str = None,
        title: str = None,
        created_at: str = None,  # Renamed from timestamp for consistency
        updated_at: str = None,  # New field for consistency
        summary: str = None,  # New field for summary support
        status: int = 1,  # New field for active/inactive status
        systemMeta: SystemMetadataModel = None,
    ):
        self.id = id if id else str(uuid4())
        self.user_id = user_id
        self.session_id = self.id  # Added for consistency with the schema
        self.correlation_id = correlation_id
        self.title = title if title else f"Session {datetime.datetime.today().strftime('%Y-%m-%d')}"

        # Use ISO format timestamp for consistency
        now = datetime.datetime.now(pytz.UTC).isoformat()
        self.created_at = created_at if created_at else now
        self.updated_at = updated_at if updated_at else now

        self.summary = summary
        self.status = status
        self.systemMeta = systemMeta if systemMeta else SystemMetadataModel(_insertedBy=user_id, _updatedBy=user_id)

    def to_json(self):
        """Convert to JSON representation compatible with the storage."""
        schema = ChatSessionSchema()
        result = schema.dump(self)
        return result

    @classmethod
    def from_json(cls, chat_session_json: Any | list[Any] | list):
        """Create from JSON data, supporting both old and new field names."""
        schema = ChatSessionSchema()

        # Map field names for compatibility
        mapped_data = chat_session_json.copy() if isinstance(chat_session_json, dict) else chat_session_json

        # Handle old field names from the previous schema
        if isinstance(mapped_data, dict):
            if "memberId" in mapped_data and "user_id" not in mapped_data:
                mapped_data["user_id"] = mapped_data.pop("memberId")

            if "timestamp" in mapped_data and "created_at" not in mapped_data:
                # Convert timestamp if it's a number
                if isinstance(mapped_data["timestamp"], (int, float)):
                    mapped_data["created_at"] = datetime.datetime.fromtimestamp(
                        mapped_data["timestamp"], pytz.UTC
                    ).isoformat()
                else:
                    mapped_data["created_at"] = mapped_data.pop("timestamp")

            # Set updated_at if not present
            if "updated_at" not in mapped_data:
                if "systemMeta" in mapped_data and "_updatedDateTime" in mapped_data["systemMeta"]:
                    mapped_data["updated_at"] = mapped_data["systemMeta"]["_updatedDateTime"]
                else:
                    mapped_data["updated_at"] = mapped_data.get(
                        "created_at", datetime.datetime.now(pytz.UTC).isoformat()
                    )

        data = schema.load(mapped_data)
        return cls(**data)


# Define a schema for serializing and deserializing the data model
class ChatSessionSchema(Schema):
    """Schema for serializing and deserializing chat sessions."""

    class Meta:
        unknown = EXCLUDE

    """A single chat session for a particular user."""
    id = fields.Str(dump_default=str(uuid4()))
    user_id = fields.Str(required=True)
    session_id = fields.Str(dump_default=lambda: str(uuid4()))
    correlation_id = fields.Str(required=True)
    title = fields.Str(required=False, allow_none=True)
    created_at = fields.Str(dump_default=lambda: datetime.datetime.now(pytz.UTC).isoformat())
    updated_at = fields.Str(dump_default=lambda: datetime.datetime.now(pytz.UTC).isoformat())
    summary = fields.Str(allow_none=True)
    status = fields.Int(dump_default=1)
    systemMeta = fields.Nested(SystemMetadataSchema, required=True)
