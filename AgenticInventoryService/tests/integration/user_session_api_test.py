import pytest
from fastapi.testclient import TestClient
from agentic_inventory.main import app

from unittest.mock import patch, MagicMock
from agentic_inventory.backend.models.chat_session_model import ChatSessionModel
from agentic_inventory.backend.models.system_metadata_model import SystemMetadataModel
import uuid

# Test client
client = TestClient(app)

# Test data
TEST_USER_ID = "test_user_123"
TEST_SESSION_TITLE = "Test Chat Session"
TEST_QUESTION = "What is the property id for Tuscany Village, a Hilton Grand Vacations Club?"
TEST_MESSAGE_CONTENT = "What is the property id for Tuscany Village, a Hilton Grand Vacations Club?"


@pytest.fixture(autouse=True)
def setup_and_cleanup():
    """Setup and cleanup for each test"""
    # Mock the storage client to avoid actual database operations
    with patch("agentic_inventory.backend.storage.storage.get_storage_client") as mock_get_storage:
        mock_storage = MagicMock()
        mock_storage._validate_session.return_value = True

        # Create a test session model with required fields
        test_session = ChatSessionModel(
            id=str(uuid.uuid4()),
            user_id=TEST_USER_ID,
            title=TEST_SESSION_TITLE,
            correlation_id=str(uuid.uuid4()),
            systemMeta=SystemMetadataModel(_insertedBy=TEST_USER_ID, _updatedBy=TEST_USER_ID, status=1),
        )

        # Set up mock responses
        mock_storage.create_chat_session.return_value = test_session.to_json()
        mock_storage.get_chat_sessions.return_value = [test_session.to_json()]
        mock_storage.get_session_messages.return_value = [
            {
                "id": str(uuid.uuid4()),
                "session_id": test_session.id,
                "user_id": TEST_USER_ID,
                "content": TEST_QUESTION,
                "role": "user",
            }
        ]
        mock_get_storage.return_value = mock_storage
        yield


def test_health_check():
    """Test health check endpoint"""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


def test_create_user_session():
    """Test creating a new chat session"""
    response = client.post(f"/api/users/{TEST_USER_ID}/sessions")
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert "correlation_id" in data
    assert data["user_id"] == TEST_USER_ID
    assert data["title"].startswith("New Conversation")


def test_get_user_sessions():
    """Test getting all sessions for a user"""
    response = client.get(f"/api/users/{TEST_USER_ID}/sessions")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert any(session["title"] == TEST_SESSION_TITLE for session in data)


def test_get_session_messages():
    """Test getting messages for a session"""
    # Create a session and add a message
    session_response = client.post(f"/api/users/{TEST_USER_ID}/sessions", json={"title": TEST_SESSION_TITLE})
    session_id = session_response.json()["id"]

    # Add a message
    response = client.post(
        f"/api/users/{TEST_USER_ID}/sessions/{session_id}/messages", json={"question": TEST_QUESTION}
    )
    assert response.status_code == 200

    # Get messages
    response = client.get(f"/api/users/{TEST_USER_ID}/sessions/{session_id}/messages")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert any(msg["content"] == TEST_QUESTION for msg in data)


def test_process_query():
    """Test processing a query in a session"""
    # Create a session first
    session_response = client.post(f"/api/users/{TEST_USER_ID}/sessions", json={"title": TEST_SESSION_TITLE})
    session_id = session_response.json()["id"]

    # Process a query
    response = client.post(
        f"/api/users/{TEST_USER_ID}/sessions/{session_id}/messages", json={"question": TEST_QUESTION}
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "metadata" in data
    assert isinstance(data["metadata"], dict)


def test_process_query_invalid_payload():
    """Test processing a query with invalid payload"""
    # Create a session first
    session_response = client.post(f"/api/users/{TEST_USER_ID}/sessions", json={"title": TEST_SESSION_TITLE})
    session_id = session_response.json()["id"]

    # Try to process with invalid payload
    response = client.post(f"/api/users/{TEST_USER_ID}/sessions/{session_id}/messages", json={"invalid": "payload"})
    assert response.status_code == 422  # Validation error


def test_process_query_empty_question():
    """Test processing a query with empty question"""
    # Create a session first
    session_response = client.post(f"/api/users/{TEST_USER_ID}/sessions", json={"title": TEST_SESSION_TITLE})
    session_id = session_response.json()["id"]

    # Try to process empty query
    response = client.post(f"/api/users/{TEST_USER_ID}/sessions/{session_id}/messages", json={"question": ""})
    assert response.status_code == 422  # Validation error


def test_get_nonexistent_session_messages():
    """Test getting messages for a nonexistent session"""
    with patch("agentic_inventory.backend.storage.storage.get_storage_client") as mock_get_storage:
        mock_storage = MagicMock()
        mock_storage._validate_session.return_value = False
        mock_get_storage.return_value = mock_storage

        response = client.get(f"/api/users/{TEST_USER_ID}/sessions/nonexistent_session/messages")
        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]


def test_process_query_nonexistent_session():
    """Test processing a query in a nonexistent session"""
    with patch("agentic_inventory.backend.storage.storage.get_storage_client") as mock_get_storage:
        mock_storage = MagicMock()
        mock_storage._validate_session.return_value = False
        mock_get_storage.return_value = mock_storage

        response = client.post(
            f"/api/users/{TEST_USER_ID}/sessions/nonexistent_session/messages", json={"question": TEST_QUESTION}
        )
        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]
