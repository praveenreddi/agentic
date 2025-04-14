"""
Unified Cosmos DB client for the Agentic Inventory Service.

This module provides a centralized interface for all Azure Cosmos DB operations,
including user sessions, session messages, job configurations, and job executions.
"""

import uuid
from typing import Dict, List, Any, Optional
from datetime import datetime

from agentic_inventory.backend.storage.storage import get_storage_client
from agentic_inventory.utils.extensions import logger
from agentic_inventory.utils.utils import get_utc_now
from agentic_inventory.utils.measure import measure_ts


class StorageSessionsClient:
    """Repository for storing and retrieving data in Cosmos DB.

    This unified repository handles all cosmos DB operations including:
    - User sessions
    - Session messages
    """

    def __init__(self):
        self.user_sessions_container = get_storage_client().user_sessions_container
        self.session_messages_container = get_storage_client().session_messages_container

    @measure_ts
    def create_user_session(
        self, user_id: str, title: Optional[str] = None, correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new session for a user.

        Args:
            user_id: The user ID
            title: Optional session title
            correlation_id: Optional correlation ID

        Returns:
            Dict: Created session data
        """
        session_id = str(uuid.uuid4())
        now = get_utc_now()

        session_data = {
            "id": session_id,
            "user_id": user_id,
            "session_id": session_id,
            "title": title or f"Session {datetime.now().strftime('%Y-%m-%d')}",
            "created_at": now,
            "updated_at": now,
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "summary": None,
            "status": 1,
        }

        try:
            result = self.user_sessions_container.create_item(body=session_data)
            logger.info(f"Created session {session_id} for user {user_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to create session: {str(e)}")
            raise

    @measure_ts
    def get_user_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all sessions for a user."""
        try:
            # Get all sessions
            query = "SELECT * FROM c WHERE c.user_id = @user_id AND c.status = 1 ORDER BY c.created_at DESC"
            params = [{"name": "@user_id", "value": user_id}]

            sessions = list(
                self.user_sessions_container.query_items(
                    query=query,
                    parameters=params,
                    enable_cross_partition_query=True,
                )
            )

            # For each session, get the last message and message count
            for session in sessions:
                try:
                    # Get last message - wrapped in try/except to handle errors
                    last_message_query = """
                        SELECT TOP 1 content, role, created_at
                        FROM c
                        WHERE c.session_id = @session_id
                        ORDER BY c.created_at DESC
                    """
                    last_message_params = [{"name": "@session_id", "value": session["session_id"]}]
                    try:
                        last_message = list(
                            self.session_messages_container.query_items(
                                query=last_message_query,
                                parameters=last_message_params,
                                enable_cross_partition_query=True,
                            )
                        )
                        session["last_message"] = last_message[0] if last_message else None
                    except Exception as e:
                        logger.error(f"Error fetching last message for session {session['id']}: {str(e)}")
                        session["last_message"] = None

                    # Get message count - wrapped in try/except to handle errors
                    try:
                        count_query = "SELECT VALUE COUNT(1) FROM c WHERE c.session_id = @session_id"
                        count_params = [{"name": "@session_id", "value": session["session_id"]}]
                        message_count = list(
                            self.session_messages_container.query_items(
                                query=count_query,
                                parameters=count_params,
                                enable_cross_partition_query=True,
                            )
                        )
                        session["message_count"] = message_count[0] if message_count else 0
                    except Exception as e:
                        logger.error(f"Error fetching message count for session {session['id']}: {str(e)}")
                        session["message_count"] = 0
                except Exception as e:
                    logger.error(f"Error processing session {session['id']}: {str(e)}")
                    session["last_message"] = None
                    session["message_count"] = 0

            logger.info(f"Retrieved {len(sessions)} sessions for user {user_id}")
            return sessions
        except Exception as e:
            logger.error(f"Failed to get sessions for user {user_id}: {str(e)}")
            raise

    def _validate_session(self, user_id: str, session_id: str) -> bool:
        """Validate that a session exists and belongs to the user.

        Args:
            user_id: The user ID
            session_id: The session ID

        Returns:
            bool: True if session exists and belongs to user, False otherwise
        """
        try:
            query = "SELECT VALUE COUNT(1) FROM c WHERE c.user_id = @user_id AND c.id = @session_id AND c.status = 1"
            params = [{"name": "@user_id", "value": user_id}, {"name": "@session_id", "value": session_id}]

            result = list(
                self.user_sessions_container.query_items(
                    query=query,
                    parameters=params,
                    enable_cross_partition_query=True,
                )
            )

            return bool(result and result[0] > 0)
        except Exception as e:
            logger.error(f"Failed to validate session {session_id} for user {user_id}: {str(e)}")
            return False

    @measure_ts
    def update_session_summary(self, session_id: str, user_id: str, summary: str = None, title: str = None) -> bool:
        """Update the summary and/or title for a session.

        Args:
            session_id: The session ID
            user_id: The user ID
            summary: Optional new summary
            title: Optional new title

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            session = self.get_session_by_id(user_id, session_id)
            if not session:
                return False

            # Update summary if provided
            if summary is not None:
                session["summary"] = summary

            # Update title if provided
            if title is not None:
                session["title"] = title

            # Update the timestamp
            session["updated_at"] = get_utc_now()

            # Update the item
            self.user_sessions_container.replace_item(item=session_id, body=session)
            logger.info(f"Updated session {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update session {session_id}: {str(e)}")
            return False

    def _update_session_timestamp(self, session_id: str, user_id: str) -> bool:
        """Update the updated_at timestamp for a session.

        Args:
            session_id: The session ID
            user_id: The user ID

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Validate session exists and belongs to user
            if not self._validate_session(user_id, session_id):
                return False

            # Get the session
            query = "SELECT * FROM c WHERE c.user_id = @user_id AND c.id = @session_id AND c.status = 1"
            params = [{"name": "@user_id", "value": user_id}, {"name": "@session_id", "value": session_id}]

            result = list(
                self.user_sessions_container.query_items(
                    query=query,
                    parameters=params,
                    enable_cross_partition_query=True,
                )
            )

            if not result:
                return False

            session = result[0]

            # Update the timestamp
            session["updated_at"] = get_utc_now()

            # Update the item
            self.user_sessions_container.replace_item(item=session["id"], body=session)
            return True
        except Exception as e:
            logger.error(f"Failed to update timestamp for session {session_id}: {str(e)}")
            return False

    # ===== Session Message Methods =====

    def _get_next_sequence_number(self, session_id: str) -> int:
        """Get the next sequence number for a message in a session.

        Args:
            session_id: The session ID

        Returns:
            int: The next sequence number
        """
        try:
            query = """
            SELECT VALUE MAX(c.sequence_number)
            FROM c
            WHERE c.session_id = @session_id
            """

            params = [{"name": "@session_id", "value": session_id}]

            results = list(
                self.session_messages_container.query_items(
                    query=query,
                    parameters=params,
                    enable_cross_partition_query=True,
                )
            )

            # Get the max sequence number and add 1
            max_seq = results[0] if results and results[0] is not None else 0
            return max_seq + 1
        except Exception as e:
            logger.error(f"Error getting next sequence number: {str(e)}")
            return 1  # Default to 1 if there's an error

    @measure_ts
    def create_session_message(
        self, session_id: str, user_id: str, content: str, role: str, metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new message in a session.

        Args:
            session_id: The session ID
            user_id: The user ID
            content: The message content
            role: Message role (user, system, bot)
            metadata: Optional metadata

        Returns:
            Dict: Created message data
        """
        # Validate session exists and belongs to user
        if not self._validate_session(user_id, session_id):
            raise ValueError(f"Session {session_id} not found for user {user_id}")

        message_id = str(uuid.uuid4())

        # Get next sequence number
        sequence_number = self._get_next_sequence_number(session_id)

        message_data = {
            "id": message_id,
            "message_id": message_id,
            "session_id": session_id,
            "user_id": user_id,
            "content": content,
            "role": role,
            "sequence_number": sequence_number,
            "created_at": get_utc_now(),
            "was_summarized": False,
        }

        # Add metadata if provided
        if metadata:
            message_data["metadata"] = metadata

        try:
            result = self.session_messages_container.create_item(body=message_data)

            # Update session's updated_at timestamp
            self._update_session_timestamp(session_id, user_id)

            logger.info(f"Created message in session {session_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to create message in session {session_id}: {str(e)}")
            raise

    @measure_ts
    def get_session_messages(self, session_id: str, user_id: str = None) -> List[Dict[str, Any]]:
        """Get all messages for a session.

        Args:
            session_id: The session ID
            user_id: Optional user ID for validation

        Returns:
            List of message objects
        """
        # Validate session exists and belongs to user if user_id provided
        if user_id and not self._validate_session(user_id, session_id):
            raise ValueError(f"Session {session_id} not found for user {user_id}")

        try:
            query_parts = ["c.session_id = @session_id"]
            params = [{"name": "@session_id", "value": session_id}]

            # Add user_id filter if provided
            if user_id:
                query_parts.append("c.user_id = @user_id")
                params.append({"name": "@user_id", "value": user_id})

            query = f"SELECT * FROM c WHERE {' AND '.join(query_parts)} ORDER BY c.sequence_number ASC"

            result = list(
                self.session_messages_container.query_items(
                    query=query,
                    parameters=params,
                    enable_cross_partition_query=True,
                )
            )

            logger.info(f"Retrieved {len(result)} messages for session {session_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to get messages for session {session_id}: {str(e)}")
            raise

    @measure_ts
    def mark_messages_as_summarized(self, session_id: str, message_ids: List[str]) -> bool:
        """Mark messages as summarized.

        Args:
            session_id: The session ID
            message_ids: List of message IDs to mark

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            for message_id in message_ids:
                # Get the message
                query = "SELECT * FROM c WHERE c.session_id = @session_id AND c.id = @message_id"
                params = [{"name": "@session_id", "value": session_id}, {"name": "@message_id", "value": message_id}]

                result = list(
                    self.session_messages_container.query_items(
                        query=query,
                        parameters=params,
                        enable_cross_partition_query=True,
                    )
                )

                if result:
                    message = result[0]
                    message["was_summarized"] = True
                    self.session_messages_container.replace_item(item=message["id"], body=message)

            logger.info(f"Marked {len(message_ids)} messages as summarized in session {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to mark messages as summarized: {str(e)}")
            return False

    @measure_ts
    def get_user_id_for_session(self, session_id: str) -> Optional[str]:
        """Get the user_id associated with a session.

        Args:
            session_id: The session ID

        Returns:
            Optional[str]: The user_id if found, None otherwise
        """
        query = "SELECT c.user_id FROM c WHERE c.id = @session_id AND c.status = 1"
        params = [{"name": "@session_id", "value": session_id}]
        result = list(
            self.user_sessions_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True,
            )
        )
        return result[0]["user_id"] if result else None

    @measure_ts
    def get_session_by_id(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a session by its ID and user_id.

        Args:
            user_id: The user ID
            session_id: The session ID

        Returns:
            Optional[Dict[str, Any]]: The session data if found, None otherwise
        """
        query = "SELECT * FROM c WHERE c.user_id = @user_id AND c.id = @session_id AND c.status = 1"
        params = [{"name": "@user_id", "value": user_id}, {"name": "@session_id", "value": session_id}]
        result = list(
            self.user_sessions_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True,
            )
        )
        return result[0] if result else None

    @measure_ts
    def get_unsummarized_messages(self, session_id: str, user_id: str) -> List[Dict[str, Any]]:
        """Get messages that haven't been summarized yet.

        Args:
            session_id: The session ID
            user_id: The user ID

        Returns:
            List[Dict[str, Any]]: List of unsummarized messages
        """
        messages = self.get_session_messages(session_id, user_id)
        return [m for m in messages if not m.get("was_summarized")]

    @measure_ts
    def get_highest_summarized_sequence(self, session_id: str, user_id: str) -> int:
        """Get the highest sequence number of summarized messages.

        Args:
            session_id: The session ID
            user_id: The user ID

        Returns:
            int: The highest sequence number
        """
        messages = self.get_session_messages(session_id, user_id)
        summarized_messages = [m for m in messages if m.get("was_summarized")]
        return max(m["sequence_number"] for m in summarized_messages) if summarized_messages else 0
