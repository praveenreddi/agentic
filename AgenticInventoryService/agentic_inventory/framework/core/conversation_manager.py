"""
Conversation Manager for the framework.

This module provides functionality to track and manage conversations
with context preservation across multiple interactions.
"""

import time
import threading
from typing import Dict, List, Any, Optional
from agentic_inventory.utils.extensions import logger
from agentic_inventory.framework.llm.openai_client import get_openai_response
from agentic_inventory.backend.storage.storage_sessions import StorageSessionsClient


class ConversationManager:
    """Manages conversations and their context for the framework."""

    def __init__(self, repository=None, default_app_name="default", default_user_id="TEST"):
        # Use the unified Cosmos client by default
        self.repository = repository or StorageSessionsClient()
        self.default_app_name = default_app_name
        self.default_user_id = default_user_id
        self.summarization_tasks = {}  # Track ongoing summarization tasks
        self.summary_threshold = 6  # Number of messages that triggers summarization
        self.sessions_by_id = {}  # Cache to store user_id by session_id

    def create_conversation(self, app_name=None, user_id=None) -> str:
        """Create a new conversation."""
        app_name = app_name or self.default_app_name

        # Set default user_id as "TEST" if None
        if user_id is None:
            user_id = self.default_user_id
            logger.info(
                "[USER_ID] Using default user_id '" + user_id + "' for new conversation with app_name " + app_name
            )

        # Create the session using the unified client
        result = self.repository.create_user_session(user_id=user_id, title=app_name, correlation_id=None)
        session_id = result["id"]

        # Store this association for later use
        self.sessions_by_id[session_id] = user_id
        logger.info(f"[USER_ID] Stored user_id '{user_id}' for session {session_id}")

        # Initialize tracking for this conversation
        self.summarization_tasks[session_id] = {"status": "not_started", "last_run": None}

        logger.info("Created new conversation " + session_id + " in Cosmos DB")
        return session_id

    def add_message(
        self,
        session_id: str,
        content: str,
        role: str,
        latency_ms: Optional[int] = None,
        tokens_consumed: Optional[Dict[str, int]] = None,
        functions_executed: Optional[List[Dict[str, Any]]] = None,
        user_id: Optional[str] = None,
        llm_model: Optional[str] = None,
        llm_provider: Optional[str] = None,
    ) -> str:
        """Add a message to an existing conversation.

        Args:
            session_id: The conversation UUID
            content: The message content
            role: The role of the sender (e.g., "user", "system")
            latency_ms: Optional latency in milliseconds
            tokens_consumed: Optional dictionary of token usage
            functions_executed: Optional list of functions executed
            user_id: Optional user identifier (defaults to "TEST" if None)
            llm_model: Optional LLM model identifier
            llm_provider: Optional LLM provider name

        Returns:
            str: The UUID of the created message
        """
        # Get user_id from session cache if not provided
        if user_id is None:
            user_id = self.sessions_by_id.get(session_id)
            if user_id is None:
                # Try to get the user_id from the session in the database
                user_id = self.repository.get_user_id_for_session(session_id)
                if user_id is None:
                    # Only use default if we can't find the user_id anywhere
                    user_id = self.default_user_id
                    logger.info(
                        "[USER_ID] Using default user_id '" + user_id + "' for message in conversation " + session_id
                    )

        # Store this association for later use
        self.sessions_by_id[session_id] = user_id

        # Prepare metadata
        metadata = {}
        if latency_ms is not None:
            metadata["latency_ms"] = latency_ms
        if tokens_consumed is not None:
            metadata["tokens_consumed"] = tokens_consumed
        if functions_executed is not None:
            metadata["functions_executed"] = functions_executed
        if llm_provider is not None:
            metadata["llm_provider"] = llm_provider

        # Create message using the unified client
        result = self.repository.create_session_message(
            session_id=session_id, user_id=user_id, content=content, role=role, metadata=metadata
        )

        message_id = result["id"]
        logger.info("Added message " + message_id + " to conversation " + session_id + " in Cosmos DB")

        # Check if we need to trigger summarization after adding this message
        self.check_and_trigger_summarization(session_id, user_id)

        return message_id

    def get_context(self, session_id: str, max_recent_messages: int = 5) -> str:
        """Get conversation context for use in LLM prompts.

        This implements the context management logic:
        - For conversations with fewer than 12 messages, return all messages
        - For longer conversations, if a summary exists:
            - Return the summary + the most recent messages
        - For longer conversations without a summary:
            - Return just the most recent messages

        Args:
            session_id: The conversation UUID
            max_recent_messages: Maximum number of recent messages to include

        Returns:
            str: The conversation context as a formatted string for use in prompts
        """
        logger.info("[CONTEXT LOG] Getting context for conversation ID: " + session_id)

        try:
            # Get the user_id from our session cache or use default
            user_id = self.sessions_by_id.get(session_id, self.default_user_id)

            # Validate session exists and belongs to user
            if not self.repository._validate_session(user_id, session_id):
                logger.info("[CONTEXT LOG] Conversation " + session_id + " not found")
                return ""

            # Get the session
            session = self.repository.get_session_by_id(user_id, session_id)
            if not session:
                logger.info("[CONTEXT LOG] Conversation " + session_id + " not found")
                return ""

            # Get all messages for the session
            messages = self.repository.get_session_messages(session_id=session_id)
            message_count = len(messages)
            logger.info("[CONTEXT LOG] Found " + str(message_count) + " total messages")

            # For short conversations, just return all messages
            if message_count < 12:
                logger.info("[CONTEXT LOG] Short conversation (<12 messages), including all messages")
                return self._format_messages_for_context(messages)

            # For longer conversations, check if summary is available
            summary = session.get("summary")

            # Check our in-memory tracking for summarization status
            summarization_in_progress = (
                session_id in self.summarization_tasks
                and self.summarization_tasks[session_id].get("status") == "running"
            )

            # If summarization is in progress, just return recent messages
            if summarization_in_progress:
                logger.info("[CONTEXT LOG] Summarization in progress, using recent messages only")
                # Summary is being generated, fall back to just the most recent messages
                recent_messages = sorted(messages, key=lambda m: m["sequence_number"], reverse=True)[
                    :max_recent_messages
                ]
                recent_messages = sorted(recent_messages, key=lambda m: m["sequence_number"])
                return self._format_messages_for_context(recent_messages)
            elif summary:
                logger.info("[CONTEXT LOG] Using summary + " + str(max_recent_messages) + " recent messages")
                recent_messages = sorted(messages, key=lambda m: m["sequence_number"], reverse=True)[
                    :max_recent_messages
                ]
                recent_messages = sorted(recent_messages, key=lambda m: m["sequence_number"])

                context = f"CONVERSATION SUMMARY:\n{summary}\n\nRECENT MESSAGES:\n"
                context += self._format_messages_for_context(recent_messages)
                return context
            else:
                logger.info("[CONTEXT LOG] No summary available, using last " + str(max_recent_messages) + " messages")
                # No summary, just use the most recent messages
                recent_messages = sorted(messages, key=lambda m: m["sequence_number"], reverse=True)[
                    :max_recent_messages
                ]
                recent_messages = sorted(recent_messages, key=lambda m: m["sequence_number"])
                return self._format_messages_for_context(recent_messages)
        except Exception as e:
            logger.info("[CONTEXT LOG] Error getting context: " + str(e))
            return ""

    def _format_messages_for_context(self, messages: List[Dict[str, Any]]) -> str:
        """Format a list of messages for use in conversation context.

        Args:
            messages: List of message objects

        Returns:
            str: Formatted context string
        """
        # Sort messages by sequence number
        messages = sorted(messages, key=lambda m: m["sequence_number"])

        formatted_messages = []
        for message in messages:
            role = message["role"].upper()
            content = message["content"]
            formatted_messages.append(f"{role}: {content}")
            logger.info("[CONTEXT LOG] Including message - Role: " + role + ", Content: " + content[:50] + "...")

        return "\n\n".join(formatted_messages)

    def check_and_trigger_summarization(self, session_id: str, user_id: str) -> None:
        """Check if summarization should be triggered and initiate if needed.

        This implements the cyclical summarization approach:
        1. First 6 messages are summarized after the 6th message
        2. Next 6 messages are summarized after the 12th message (including previous summary)
        3. This cycle repeats every 6 messages

        Args:
            session_id: The conversation UUID
            user_id: The user ID
        """
        # Check if there's already a summarization task running for this conversation
        if session_id in self.summarization_tasks:
            task_status = self.summarization_tasks[session_id].get("status")
            if task_status == "running":
                logger.info("Summarization already in progress for " + session_id)
                return

        # Validate session exists and belongs to user
        if not self.repository._validate_session(user_id, session_id):
            logger.info("Session " + session_id + " not found")
            return

        # Get the session
        session = self.repository.get_session_by_id(user_id, session_id)
        if not session:
            logger.info("Session " + session_id + " not found")
            return

        # Get all messages
        messages = self.repository.get_session_messages(session_id, user_id)

        # Count the total number of messages (each user+system interaction counts as 2 messages)
        message_count = len(messages)

        # Check if we have enough messages to trigger summarization (after every 6 pairs, so messages 12, 24, etc.)
        # The first summarization happens after messages 1-12 (6 pairs)
        if message_count >= 12 and message_count % 12 == 0:
            logger.info("Triggering summarization for conversation " + session_id)

            # If this is a fresh summarization cycle (no previous summary)
            if not session.get("summary"):
                # Summarize all messages
                self._trigger_background_summarization(session_id, user_id, messages)
            else:
                # Get the most recent messages that haven't been summarized yet (the last 12 messages)
                unsummarized_messages = [m for m in messages if not m.get("was_summarized")]

                # Store information about what's covered by the current summary
                if session_id not in self.summarization_tasks:
                    self.summarization_tasks[session_id] = {}

                # Track the highest sequence number included in the previous summary
                summarized_messages = [m for m in messages if m.get("was_summarized")]
                highest_summarized_seq = 0
                if summarized_messages:
                    highest_summarized_seq = max(m["sequence_number"] for m in summarized_messages)

                self.summarization_tasks[session_id]["previous_summary_seq"] = highest_summarized_seq

                # We'll summarize using the previous summary + these new messages
                self._trigger_background_summarization(
                    session_id, user_id, unsummarized_messages, previous_summary=session.get("summary")
                )

    def _trigger_background_summarization(
        self, session_id: str, user_id: str, messages: List[Dict[str, Any]], previous_summary: Optional[str] = None
    ) -> None:
        """Trigger background summarization process.

        Args:
            session_id: The conversation UUID
            user_id: The user ID
            messages: The messages to summarize
            previous_summary: The previous summary to incorporate (if this is not the first summarization)
        """
        logger.info("[SUMMARIZATION] Starting background summarization for conversation " + session_id)
        logger.info("[SUMMARIZATION] Messages to summarize: " + str(len(messages)))
        logger.info("[SUMMARIZATION] Previous summary exists: " + str(previous_summary is not None))

        # Create a thread for summarization
        thread = threading.Thread(
            target=self._generate_and_store_summary, args=(session_id, user_id, messages, previous_summary)
        )
        thread.daemon = True  # Make thread a daemon so it doesn't block program exit

        # Track the task
        if session_id not in self.summarization_tasks:
            self.summarization_tasks[session_id] = {}

        self.summarization_tasks[session_id].update(
            {
                "status": "running",
                "started_at": time.time(),
                "thread": thread,
                "message_count": len(messages),
                # Track the max sequence number that will be covered by this summarization
                "max_seq_to_summarize": max(m["sequence_number"] for m in messages) if messages else 0,
            }
        )

        logger.info("[SUMMARIZATION] Thread created with ID: " + str(thread.ident))
        logger.info("[SUMMARIZATION] Starting summarization thread")

        # Start the summarization thread
        thread.start()

        logger.info("[SUMMARIZATION] Thread started, control returned to main program")

    def _generate_and_store_summary(
        self, session_id: str, user_id: str, messages: List[Dict[str, Any]], previous_summary: Optional[str] = None
    ) -> None:
        """Generate and store a summary for a conversation.

        This method runs in a background thread.

        Args:
            session_id: The conversation UUID
            user_id: The user ID
            messages: The messages to summarize
            previous_summary: The previous summary to incorporate (if this is not the first summarization)
        """
        try:
            thread_id = threading.get_ident()
            logger.info(
                "[SUMMARIZATION THREAD "
                + str(thread_id)
                + "] Starting summary generation for conversation "
                + str(session_id)
            )

            # Sort messages by sequence number
            messages.sort(key=lambda m: m["sequence_number"])

            # Format messages for the LLM
            formatted_messages = [f"{m['role'].upper()}: {m['content']}" for m in messages]
            logger.info(
                "[SUMMARIZATION THREAD "
                + str(thread_id)
                + "] Formatted "
                + str(len(formatted_messages))
                + " messages for summarization"
            )

            # If we have a previous summary, include it in the prompt
            if previous_summary:
                logger.info(
                    "[SUMMARIZATION THREAD "
                    + str(thread_id)
                    + "] Using progressive summarization with previous summary"
                )
                prompt = (
                    "I'll provide you with a previous summary of a conversation, followed by new messages. "
                    "Create a comprehensive updated summary that incorporates both the previous summary "
                    "and the new information.\n\n"
                    f"PREVIOUS SUMMARY:\n{previous_summary}\n\n"
                    "NEW MESSAGES TO INCORPORATE:\n\n" + "\n\n".join(formatted_messages)
                )
            else:
                # First-time summary
                logger.info("[SUMMARIZATION THREAD " + str(thread_id) + "] Generating first-time summary")
                prompt = (
                    "Summarize the following conversation concisely while preserving all important "
                    "information, context, and key points from both the user and system:\n\n"
                    + "\n\n".join(formatted_messages)
                )

            logger.info(
                "[SUMMARIZATION THREAD " + str(thread_id) + "] Prompt created, calling LLM for summary generation"
            )
            # Call LLM to generate summary
            start_time = time.time()
            summary = get_openai_response(prompt=prompt, json_mode=False)
            elapsed_time = time.time() - start_time
            logger.info(
                "[SUMMARIZATION THREAD " + str(thread_id) + "] LLM call completed in " + str(elapsed_time) + " seconds"
            )

            if not summary:
                logger.info(
                    "[SUMMARIZATION THREAD "
                    + str(thread_id)
                    + "] Failed to generate summary for conversation "
                    + str(session_id)
                )
                self.summarization_tasks[session_id]["status"] = "failed"
                return
            logger.info("[SUMMARIZATION THREAD " + str(thread_id) + "] Storing summary")

            # Store the summary using the unified client
            self.repository.update_session_summary(session_id, user_id, summary)

            # Mark messages as summarized
            message_ids = [m["message_id"] for m in messages]
            logger.info(
                "[SUMMARIZATION THREAD "
                + str(thread_id)
                + "] Marking "
                + str(len(message_ids))
                + " messages as summarized"
            )
            self.repository.mark_messages_as_summarized(session_id, message_ids)

            logger.info(
                "[SUMMARIZATION THREAD " + str(thread_id) + "] Successfully summarized conversation " + str(session_id)
            )
            self.summarization_tasks[session_id]["status"] = "completed"

        except Exception as e:
            thread_id = threading.get_ident()
            logger.info("[SUMMARIZATION THREAD " + str(thread_id) + "] Error during summarization: " + str(e))
            if session_id in self.summarization_tasks:
                self.summarization_tasks[session_id]["status"] = "failed"
                self.summarization_tasks[session_id]["error"] = str(e)
