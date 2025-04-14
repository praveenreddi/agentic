"""
Chat message model for the Agentic Inventory Service.

This module defines the data model for chat messages.
"""

import datetime
from typing import Literal, Dict, Any
from uuid import uuid4
import orjson
from marshmallow import Schema, SchemaOpts, fields, validate, EXCLUDE
from agentic_inventory.backend.models.system_metadata_model import SystemMetadataModel, SystemMetadataSchema


MSG_TYPE = Literal["user", "system", "bot"]


class CustomOptions(SchemaOpts):
    def __init__(self, meta, ordered=True, *args, **kwargs):
        super().__init__(meta, ordered, *args, **kwargs)
        self.dateformat = "iso"
        # the whole point of this is to set a better json ser/deser
        self.render_module = orjson
        self.ordered = ordered
        self.strict = True


class ChatMessageModel:

    def __init__(
        self,
        id: str = None,
        session_id: str = None,  # Renamed from chatSessionId for consistency
        user_id: str = None,  # Renamed from memberId for consistency
        correlation_id: str = None,
        content: str = None,  # Renamed from text for consistency
        role: MSG_TYPE = "user",  # Renamed from msgType for consistency
        sequence_number: int = None,
        created_at: str = None,  # Renamed from timestamp for consistency
        metadata: Dict[str, Any] = None,
        was_summarized: bool = False,
        systemMeta: SystemMetadataModel = None,
    ):
        self.id = id if id else str(uuid4())
        self.session_id = session_id
        self.user_id = user_id
        self.correlation_id = correlation_id
        self.content = content
        self.role = role
        self.sequence_number = sequence_number
        self.created_at = created_at if created_at else datetime.datetime.now().isoformat()
        self.metadata = metadata or {}
        self.was_summarized = was_summarized
        self.systemMeta = systemMeta if systemMeta else SystemMetadataModel(_updatedBy=user_id, _insertedBy=user_id)

    def to_json(self):
        schema = ChatMessageSchema()
        result = schema.dump(self)
        # Map old field names to new ones for backwards compatibility
        return result

    @classmethod
    def from_json(cls, chat_message_json):
        """Create from JSON data, supporting both old and new field names."""
        schema = ChatMessageSchema()

        # Map field names for compatibility
        mapped_data = chat_message_json.copy()

        # Handle old field names from the previous schema
        if "memberId" in mapped_data and "user_id" not in mapped_data:
            mapped_data["user_id"] = mapped_data.pop("memberId")

        if "chatSessionId" in mapped_data and "session_id" not in mapped_data:
            mapped_data["session_id"] = mapped_data.pop("chatSessionId")

        if "text" in mapped_data and "content" not in mapped_data:
            mapped_data["content"] = mapped_data.pop("text")

        if "msgType" in mapped_data and "role" not in mapped_data:
            mapped_data["role"] = mapped_data.pop("msgType")

        if "timestamp" in mapped_data and "created_at" not in mapped_data:
            mapped_data["created_at"] = mapped_data.pop("timestamp")

        data = schema.load(mapped_data)
        return cls(**data)


class ChatMessageSchema(Schema):
    """Schema for serializing and deserializing chat messages."""

    class Meta:
        unknown = EXCLUDE

    id = fields.Str(dump_default=str(uuid4()))
    user_id = fields.Str(required=True)  # Primary field for user id
    session_id = fields.Str(required=True)  # Primary field for session id
    correlation_id = fields.Str(required=True)
    content = fields.Str(required=True)
    role = fields.Str(validate=validate.OneOf(["user", "system", "bot"]))
    sequence_number = fields.Int(dump_default=1)
    created_at = fields.Str(dump_default=lambda: datetime.datetime.now().isoformat())
    was_summarized = fields.Bool(dump_default=False)
    metadata = fields.Dict(keys=fields.Str(), values=fields.Raw(), dump_default={})
    systemMeta = fields.Nested(SystemMetadataSchema)

    # Legacy field names for backwards compatibility
    memberId = fields.Str(dump_only=True, attribute="user_id")  # Maps to user_id when dumping
    chatSessionId = fields.Str(dump_only=True, attribute="session_id")  # Maps to session_id when dumping
    text = fields.Str(dump_only=True, attribute="content")  # Maps to content when dumping
    msgType = fields.Str(dump_only=True, attribute="role")  # Maps to role when dumping
    timestamp = fields.Str(dump_only=True, attribute="created_at")  # Maps to created_at when dumping
    conversationId = fields.Str(dump_only=True, attribute="session_id")  # Maps to session_id when dumping


class ChatMessageWithFeedbackSchema(ChatMessageSchema):
    """Extended schema for chat messages with feedback."""

    feedback = fields.Nested("ChatMessageFeedbackModel", required=False)
