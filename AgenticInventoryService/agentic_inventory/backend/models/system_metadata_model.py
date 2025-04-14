"""
System metadata model for the Agentic Inventory Service.

This module defines the metadata structure for tracking operations,
adapted to work with the storage approach.
"""

import datetime
import orjson
import pytz
from marshmallow import Schema, fields, SchemaOpts


class CustomOptions(SchemaOpts):
    """Custom options for schema serialization."""

    def __init__(self, meta, ordered=True, *args, **kwargs):
        super().__init__(meta, ordered, *args, **kwargs)
        self.dateformat = "iso"
        # the whole point of this is to set a better json ser/deser
        self.render_module = orjson
        self.ordered = ordered
        self.strict = True


class SystemMetadataModel:
    """System metadata model compatible with the storage approach."""

    def __init__(
        self,
        _insertedBy="System",
        _insertedDateTime=None,
        _updatedBy="System",
        _updatedDateTime=None,
        status=1,
        statusReason="",
    ):
        self._insertedBy = _insertedBy
        self._insertedDateTime = _insertedDateTime or datetime.datetime.now(pytz.UTC).isoformat()
        self._updatedBy = _updatedBy
        self._updatedDateTime = _updatedDateTime or datetime.datetime.now(pytz.UTC).isoformat()
        self.status = status
        self.statusReason = statusReason

    def to_json(self):
        """Convert to JSON representation."""
        return SystemMetadataSchema().dump(self)

    @classmethod
    def from_json(cls, metadata_json):
        """Create from JSON data."""
        schema = SystemMetadataSchema()
        data = schema.load(metadata_json)
        return cls(**data)

    def update(self, updated_by="System"):
        """Update the metadata with current timestamp."""
        self._updatedBy = updated_by
        self._updatedDateTime = datetime.datetime.now(pytz.UTC).isoformat()
        return self

    def mark_deleted(self, reason="", deleted_by="System"):
        """Mark this metadata as deleted (inactive)."""
        self.status = 0
        self.statusReason = reason or "Deleted"
        self._updatedBy = deleted_by
        self._updatedDateTime = datetime.datetime.now(pytz.UTC).isoformat()
        return self

    def is_active(self):
        """Check if this metadata represents an active record."""
        return self.status == 1


class SystemMetadataSchema(Schema):
    """Schema for serializing and deserializing system metadata."""

    """The following is a model for the OneTruth meta fields."""
    _insertedBy = fields.Str(required=True)
    _insertedDateTime = fields.Str(
        required=True,
        dump_default=lambda: datetime.datetime.now(pytz.UTC).isoformat(),
    )
    _updatedBy = fields.Str(required=True)
    _updatedDateTime = fields.Str(dump_default=lambda: datetime.datetime.now(pytz.UTC).isoformat())

    """Status for soft deletes. 1 is active."""
    status = fields.Int(dump_default=1, load_default=1)

    """The reason for the delete."""
    statusReason = fields.Str(dump_default="")

    class Meta:
        """Schema meta options."""

        ordered = True
