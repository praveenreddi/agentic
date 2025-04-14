"""
Utility functions for the HGV Framework API.
"""

import json
import pytz

from datetime import datetime
from typing import Dict, Any, Optional
from agentic_inventory.utils.extensions import logger


def format_error_response(
    error_message: str, error_type: str = "ProcessingError", status_code: int = 500
) -> Dict[str, Any]:
    """
    Format an error response for the API.

    Args:
        error_message: The error message
        error_type: The type of error
        status_code: The HTTP status code

    Returns:
        A formatted error response
    """
    return {"error": {"type": error_type, "message": error_message, "status_code": status_code}}


def get_session_id(response: Dict[str, Any]) -> Optional[str]:
    """
    Extract the conversation ID from a response.

    Args:
        response: The response from framework

    Returns:
        The conversation ID if found, None otherwise
    """
    # Check top level
    if "session_id" in response:
        return response["session_id"]

    # Check metadata
    if "metadata" in response and isinstance(response["metadata"], dict):
        metadata = response["metadata"]
        if "session_id" in metadata:
            return metadata["session_id"]

    return None


def sanitize_response(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize the response from the framework.

    This function ensures the response is JSON-serializable and cleans up any
    internal data that shouldn't be exposed to the client.

    Args:
        response: The raw response from framework

    Returns:
        A sanitized response
    """
    # Make a copy of the response to avoid modifying the original
    sanitized = response.copy()

    # Remove any sensitive or unnecessary fields
    keys_to_remove = [
        # Add keys to remove here if needed
    ]

    for key in keys_to_remove:
        if key in sanitized:
            del sanitized[key]

    # Ensure the response is JSON-serializable
    try:
        # Test JSON serialization
        json.dumps(sanitized)
        return sanitized
    except (TypeError, ValueError) as e:
        # If there's an issue, convert problematic values to strings
        logger.info("JSON serialization issue", extra={"error": str(e)})
        return _make_serializable(sanitized)


def _make_serializable(obj: Any) -> Any:
    """
    Convert an object to a JSON-serializable format.

    Args:
        obj: The object to convert

    Returns:
        A JSON-serializable version of the object
    """
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_make_serializable(i) for i in obj]
    elif isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    else:
        # Convert other types to string
        return str(obj)


def log_request(user_id: str, session_id: Optional[str], question: str) -> None:
    """
    Log a request to the API.

    Args:
        user_id: The user ID
        session_id: The conversation ID (if any)
        question: The user's question
    """
    logger.info(
        "API Request",
        extra={"user_id": user_id, "session_id": session_id or "NEW", "question_length": len(question)},
    )


def get_utc_now():
    """Get current UTC time as an ISO formatted string."""
    return datetime.now(pytz.UTC).isoformat()
