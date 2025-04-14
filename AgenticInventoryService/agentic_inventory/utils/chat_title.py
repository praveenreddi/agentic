"""
Chat title generator for the Agentic Inventory Service.

This module provides functionality to generate titles for chat sessions
using LLM.
"""

import threading
import datetime
from openai import AzureOpenAI

from agentic_inventory.backend.models.chat_message_model import ChatMessageModel
from agentic_inventory.utils.extensions import logger
from agentic_inventory.utils import config
from agentic_inventory.backend.storage.storage_sessions import StorageSessionsClient


class ChatTitleGenerator:
    """Generates titles for chat sessions using LLM."""

    def __init__(self):
        """Initialize the ChatTitleGenerator."""
        self.storage_client = StorageSessionsClient()
        try:
            self.llm = AzureOpenAI(
                api_key=config.AZURE_OPENAI_API_KEY.get_secret_value(),
                api_version=config.AZURE_OPENAI_API_VERSION,
                azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            )
            logger.info(f"Chat Title started model {config.AZURE_OPENAI_ENDPOINT}")
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {str(e)}")
            raise

    def generate_title(self, chat_message: ChatMessageModel, user_session_messages, current_title) -> str:
        """
        Generates a concise title for a chat session based on the user query.

        Args:
            chat_message: The chat message that triggered title generation
            user_session_messages: Previous user messages in the session
            current_title: The current session title

        Returns:
            str: A short title for the chat session. If an error occurs, returns an error message.
        """
        query = chat_message.content.strip()  # Use content instead of text
        prompt = f"""
        Review the following user query and chat history to determine if the current title is appropriate.
        Only generate a new title if:
        1. The user query contains something new, unique, or specific that was not part of the previous conversation.
        2. The current title is not suitable or meaningful given the user query and history.
        3. Do NOT generate a new title if the current User Query is generic (like "hey", "hello", etc.),
        and the existing title is already meaningful and descriptive. in this case, return the current title unchanged.

        If the existing title is suitable based on the query and history, return the current title unchanged.
        If the title is not suitable, but the current User Query and History contain only generic phrases
            like "Hey", "Hello", or other non-descriptive content, return the current title unchanged.

        Return either the current title or a new concise title, maximum 5 words, based on the context:

        Current Title: {current_title}
        User Query: {query}
        History: {user_session_messages}
        """

        try:
            response = self.llm.invoke(prompt)
            title = response.content if hasattr(response, "content") else str(response)
            logger.info(f"Generated title before truncation: {title}")

            words = title.strip().split()
            short_title = " ".join(words)
            logger.info(f"Final short title: {short_title}")
            return short_title

        except Exception as e:
            logger.error(f"An error occurred while generating the title: {e}")
            query_words = query.split()
            fallback_title = " ".join(query_words)
            return fallback_title if fallback_title else f"Session {datetime.datetime.today().strftime('%Y-%m-%d')}"

    def title_callback(self, chat_title, session):
        """
        Update the session title in the database.

        Args:
            chat_title: The generated title
            session: The session object to update
        """
        if chat_title:
            try:
                user_id = session.user_id if hasattr(session, "user_id") else session.get("user_id")
                session_id = session.id if hasattr(session, "id") else session.get("id")

                if not user_id or not session_id:
                    logger.error("Cannot update title: Missing user_id or session_id in session object")
                    return

                # Update the session object
                success = self.storage_client.update_session_summary(
                    session_id=session_id,
                    user_id=user_id,
                    summary=session.get("summary") if isinstance(session, dict) else getattr(session, "summary", None),
                    title=chat_title,  # Add the title parameter here
                )

                if success:
                    logger.info(f"Updated session {session_id} with title: {chat_title}")
                else:
                    logger.error(f"Failed to update session {session_id} with title: {chat_title}")
            except Exception as e:
                logger.error(f"Error updating session title: {str(e)}")

    def start_title_generation_thread(self, chat_message: ChatMessageModel):
        """
        Starts a background thread to handle the title generation.

        Args:
            chat_message: The message that triggered title generation
        """

        def title_update_task():
            try:
                logger.info(f"Starting title generation thread for chat message: {chat_message}")
                # Get user_id from the message
                user_id = (
                    chat_message.user_id
                    if hasattr(chat_message, "user_id")
                    else getattr(chat_message, "memberId", None)
                )
                if not user_id:
                    logger.error("Cannot generate title: No user_id found in chat message")
                    return

                # Get session_id from the message
                session_id = (
                    chat_message.session_id
                    if hasattr(chat_message, "session_id")
                    else getattr(chat_message, "chatSessionId", None)
                )
                if not session_id:
                    logger.error("Cannot generate title: No session_id found in chat message")
                    return

                # Get the session directly instead of getting all sessions
                query = "SELECT * FROM c WHERE c.user_id = @user_id AND c.id = @session_id AND c.status = 1"
                params = [{"name": "@user_id", "value": user_id}, {"name": "@session_id", "value": session_id}]

                result = list(
                    self.storage_client.user_sessions_container.query_items(
                        query=query,
                        parameters=params,
                        enable_cross_partition_query=True,
                    )
                )

                if not result:
                    logger.error(f"Session {session_id} not found for user {user_id}")
                    return

                session = result[0]

                # Get user messages for this session
                messages = self.storage_client.get_session_messages(session_id=session_id, user_id=user_id)

                # Filter for only user messages and extract content
                user_session_messages = [
                    msg.get("content", msg.get("text", ""))  # Try both new and old field names
                    for msg in messages
                    if msg.get("role", msg.get("msgType", "")) == "user"  # Try both new and old field names
                ]

                current_title = session["title"]

                # Only generate title if the current one is generic and this is a user message
                is_user_message = (hasattr(chat_message, "role") and chat_message.role == "user") or (
                    hasattr(chat_message, "msgType") and chat_message.msgType == "user"
                )
                logger.info(
                    f"Title generation condition check: "
                    f"messages={len(user_session_messages)}, "
                    f"current_title={current_title}"
                )
                if (
                    len(user_session_messages) <= 3
                    and (current_title.startswith("Session") or current_title.startswith("New Conversation"))
                    and is_user_message
                ):
                    logger.info("Condition met, generating title")
                    chat_title = self.generate_title(chat_message, user_session_messages, current_title)

                    if chat_title and chat_title != current_title:
                        # Need to update title in session data first
                        session["title"] = chat_title

                        updated = self.storage_client.update_session_summary(
                            session_id=session["id"], user_id=user_id, summary=session.get("summary"), title=chat_title
                        )

                        if updated:
                            logger.info(f"Updated title for session {session['id']}: {chat_title}")
                        else:
                            logger.error(f"Failed to update title for session {session['id']}")
            except Exception as e:
                logger.exception(f"Failed to generate or update title for session: {e}")

        threading.Thread(target=title_update_task, daemon=True).start()
