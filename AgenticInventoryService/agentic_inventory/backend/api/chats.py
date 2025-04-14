"""
Chat API routes for the Agentic Inventory Service.

This module provides REST API endpoints for managing user chat sessions
and messages, following RESTful design principles.
"""

import uuid
import jwt
import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, status, Depends, Header
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any, Literal
from agentic_inventory.utils.extensions import logger
from agentic_inventory.backend.tools.tools import function_composer
from agentic_inventory.framework.core.nl_composer import NLComposer
from agentic_inventory.backend.models.chat_message_model import ChatMessageModel
from agentic_inventory.backend.storage.storage_sessions import StorageSessionsClient
from agentic_inventory.utils.chat_title import ChatTitleGenerator


router = APIRouter(tags=["chats"])


# Azure AD token validation settings
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")

# Flag to indicate if authentication is enabled
AUTH_ENABLED = bool(TENANT_ID and CLIENT_ID)

# Log authentication status
if AUTH_ENABLED:
    logger.info(f"Azure AD authentication enabled with tenant ID: {TENANT_ID} and client ID: {CLIENT_ID}")
else:
    logger.warning("Azure AD authentication is DISABLED! Running in unsecured mode.")


def validate_token(authorization: Optional[str] = Header(None)):
    # If authentication is disabled, return an empty payload
    if not AUTH_ENABLED:
        logger.debug("Authentication is disabled, skipping token validation")
        return {}

    if not authorization:
        # Skip validation if no token provided and return None
        logger.warning("No authorization header provided")
        return None

    if not authorization.startswith("Bearer "):
        logger.warning("Invalid authorization header format")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")

    token = authorization.replace("Bearer ", "")

    try:
        # Simple decode without signature verification - just to extract and check claims
        decoded_token = jwt.decode(token, options={"verify_signature": False})

        # Log the token info for debugging
        logger.info(f"Token validated for user: {decoded_token.get('name', 'unknown')}")

        # Check if the token has the required claims
        if not decoded_token.get("sub"):
            logger.warning("Token missing subject claim")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        # Check if the token is expired
        if "exp" in decoded_token:
            import time

            current_time = int(time.time())
            if decoded_token["exp"] < current_time:
                logger.warning("Token has expired")
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")

        # Basic check for tenant ID in issuer
        issuer = decoded_token.get("iss", "")
        if TENANT_ID and TENANT_ID not in issuer:
            logger.warning(f"Token issuer {issuer} does not contain tenant ID {TENANT_ID}")
            # We'll just log this but allow it to pass for compatibility

        # Return the decoded token claims
        return decoded_token

    except jwt.PyJWTError as e:
        logger.warning(f"Invalid token: {e}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except Exception as e:
        logger.error(f"Token validation error: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token validation failed")


# Function to validate that the token's user ID matches the requested user_id
def validate_user_access(user_id: str, token_payload: Dict):
    if not AUTH_ENABLED or token_payload is None:
        return True

    # Check if the oid claim in the token matches the user_id in the path
    token_user_id = token_payload.get("oid")
    name = token_payload.get("name")
    if not token_user_id:
        logger.warning("Token missing oid claim")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User ID not found in token")

    if token_user_id != user_id:
        logger.warning(f"Token user ID {token_user_id} doesn't match requested user ID {user_id}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    logger.info(f"User {name}: {token_user_id} authorized to access this resource")
    return True


# Get Cosmos DB client
def get_storage():
    return StorageSessionsClient()


# Create NL composer with the function composer from tools.py
nl_composer = NLComposer(function_composer)

# Initialize the ChatTitleGenerator
title_generator = ChatTitleGenerator()


# Pydantic models for request/response
class SessionCreate(BaseModel):
    """Request model for creating a new chat session."""

    title: Optional[str] = None
    correlation_id: Optional[str] = None


class MessageCreate(BaseModel):
    """Request model for creating a new message in a session."""

    model_config = ConfigDict(str_strip_whitespace=True)

    content: str
    role: Literal["user", "system", "bot"] = "user"
    metadata: Optional[Dict[str, Any]] = None


class QueryRequest(BaseModel):
    """Request model for processing a query in a session."""

    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(..., description="User's question or request", min_length=1)


# === User Session Routes ===


@router.post("/users/{user_id}/sessions", status_code=status.HTTP_201_CREATED)
async def create_user_session(
    user_id: str,
    session_data: Optional[SessionCreate] = None,
    storage=Depends(get_storage),
    token_payload: Dict = Depends(validate_token),
):
    """Create a new session for a user."""
    # Check if token validation is enabled and token was provided
    if AUTH_ENABLED and token_payload is None:
        logger.warning("Authentication required but no valid token provided")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    # Validate that the token's user ID matches the requested user_id
    validate_user_access(user_id, token_payload)

    try:
        # Set defaults if no data provided
        if session_data is None:
            session_data = SessionCreate(
                title=f"New Conversation {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                correlation_id=str(uuid.uuid4()),  # Generate a random correlation_id
            )

        # Check if title is None OR equals "string" and set a default
        if session_data.title is None or session_data.title == "string" or not session_data.title.strip():
            session_data.title = f"New Conversation {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        # Check if correlation_id is None OR equals "string" and generate one
        if (
            session_data.correlation_id is None
            or session_data.correlation_id == "string"
            or not session_data.correlation_id.strip()
        ):
            session_data.correlation_id = str(uuid.uuid4())

        # Create the session
        result = storage.create_user_session(
            user_id=user_id, title=session_data.title, correlation_id=session_data.correlation_id
        )

        logger.info(f"Created session for user {user_id} with ID {result['id']}")
        return result
    except Exception as e:
        logger.error(f"Failed to create session for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create session")


@router.get("/users/{user_id}/sessions")
async def get_user_sessions(user_id: str, storage=Depends(get_storage), token_payload: Dict = Depends(validate_token)):
    """Get all sessions for a user with last message preview and message count."""
    # Check if token validation is enabled and token was provided
    if AUTH_ENABLED and token_payload is None:
        logger.warning("Authentication required but no valid token provided")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    # Validate that the token's user ID matches the requested user_id
    validate_user_access(user_id, token_payload)

    try:
        sessions = storage.get_user_sessions(user_id)
        logger.info(f"Retrieved {len(sessions)} sessions for user {user_id}")
        return sessions
    except Exception as e:
        logger.error(f"Failed to fetch sessions for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch sessions")


# === Session Message Routes ===


@router.get("/users/{user_id}/sessions/{session_id}/messages")
async def get_session_messages(
    user_id: str, session_id: str, storage=Depends(get_storage), token_payload: Dict = Depends(validate_token)
):
    """Get all messages for a session."""
    # Check if token validation is enabled and token was provided
    if AUTH_ENABLED and token_payload is None:
        logger.warning("Authentication required but no valid token provided")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    # Validate that the token's user ID matches the requested user_id
    validate_user_access(user_id, token_payload)

    try:
        # Verify session exists first
        if not storage._validate_session(user_id, session_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

        # Get the messages
        messages = storage.get_session_messages(session_id, user_id)
        logger.info(f"Retrieved {len(messages)} messages for session {session_id}")
        return messages
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch messages for session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch messages")


# === Query Processing Route ===


@router.post("/users/{user_id}/sessions/{session_id}/messages")
async def process_query(
    user_id: str,
    session_id: str,
    query: QueryRequest,
    storage=Depends(get_storage),
    token_payload: Dict = Depends(validate_token),
) -> Dict:
    """
    Process a user query using the framework.

    This endpoint handles natural language processing, executes the query,
    and stores the request and response as messages in the session.
    """
    # Check if token validation is enabled and token was provided
    if AUTH_ENABLED and token_payload is None:
        logger.warning("Authentication required but no valid token provided")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    # Validate that the token's user ID matches the requested user_id
    validate_user_access(user_id, token_payload)

    try:
        # Verify session exists
        if not storage._validate_session(user_id, session_id):
            logger.warning(f"Session {session_id} not found for user {user_id}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

        logger.info(
            "Processing user query",
        )

        # Create a ChatMessageModel for title generation
        chat_message = ChatMessageModel(
            id=session_id, session_id=session_id, user_id=user_id, content=query.question, role="user"
        )

        # Get all previous messages to check if this is one of the first messages
        messages = storage.get_session_messages(session_id, user_id)
        if len(messages) <= 3:  # Only for the first few messages
            # Trigger title generation in the background
            title_generator.start_title_generation_thread(chat_message)

        # Execute query with NL composer
        response = nl_composer.execute_from_nl(
            query.question,
            return_metadata=True,
            session_id=session_id,
            user_id=user_id,  # This is critical - ensure it matches the session owner
            app_name="AgenticInventory",
        )

        # Extract the answer and metadata
        answer = response.get("answer", "")

        # Return the response to the client
        return {
            "answer": answer,
            "metadata": {
                "tokens_consumed": response.get("tokens_consumed", {}),
                "latency_taken": response.get("latency_taken", 0),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process query: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process query")
