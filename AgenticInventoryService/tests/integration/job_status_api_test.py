import pytest
from fastapi.testclient import TestClient
import uuid
import os

from agentic_inventory.main import app
from agentic_inventory.backend.models.job_config_model import JobConfig
from agentic_inventory.backend.models.notify_config_model import NotifyConfig
from agentic_inventory.backend.models.job_model import JobStatus
from agentic_inventory.backend.jobs.service import job_service, job_config_service
from agentic_inventory.utils.extensions import logger


@pytest.fixture(autouse=True)
async def cleanup(client, test_job_name):
    """Clean up test data after each test."""
    yield
    try:
        # Delete job config if it exists
        job_config_service.delete_config(test_job_name)
    except Exception as e:
        logger.error(f"Error cleaning up test data: {str(e)}")


@pytest.fixture(autouse=True)
def check_env():
    """Check if environment variables are loaded correctly."""
    logger.info("Checking environment variables...")
    logger.info(f"COSMOSDB_ENDPOINT: {os.getenv('COSMOSDB_ENDPOINT')}")
    logger.info(f"COSMOSDB_DATABASE_NAME: {os.getenv('COSMOSDB_DATABASE_NAME')}")
    logger.info(f"COSMOSDB_ACCOUNT_KEY: {os.getenv('COSMOSDB_ACCOUNT_KEY')[:10]}...")


@pytest.fixture
def client():
    """Create a test client with initialized FastAPI application."""
    # Initialize the application
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def test_job_name():
    """Generate a unique job name for each test."""
    return f"test_job_{str(uuid.uuid4())[:8]}"


@pytest.fixture
def job_config():
    """Create a basic job configuration."""

    def _create_job_config(job_name: str):
        return JobConfig(
            id=job_name,
            job_name=job_name,
            description=f"Test job {job_name}",
            schedule="0 0 * * *",
            parameters={"test_param": "test_value"},
            notify=NotifyConfig(enabled=True, method="email"),
            timeout=300,
            retry_count=3,
            retry_delay=60,
        )

    return _create_job_config


def test_get_status_nonexistent_job(client, test_job_name):
    """Test getting status of a non-existent job."""
    response = client.get(f"/api/jobs/{test_job_name}/status")
    assert response.status_code == 404
    assert response.json()["detail"] == "Not Found"


def test_get_status_new_job(client, test_job_name, job_config):
    """Test getting status of a newly created job with no executions."""
    # Create the job config
    config = job_config(test_job_name)
    job_config_service.create_config(config)

    response = client.get(f"/api/jobs/{test_job_name}/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_started"
    assert data["result"] is None
    assert data["timestamp"] is None


def test_get_status_queued_job(client, test_job_name, job_config):
    """Test getting status of a queued job."""
    # Create job config and execution
    config = job_config(test_job_name)
    job_config_service.create_config(config)

    # Create a job execution (this will set status to QUEUED)
    job = job_service.create_job(test_job_name)

    response = client.get(f"/api/jobs/{test_job_name}/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == JobStatus.QUEUED.value
    assert data["id"] == job.id
    assert data["result"] is None


def test_get_status_executing_job(client, test_job_name, job_config):
    """Test getting status of an executing job."""
    # Create job config and execution
    config = job_config(test_job_name)
    job_config_service.create_config(config)
    job = job_service.create_job(test_job_name)

    # Update status to EXECUTING
    job_service.update_job_status(test_job_name, JobStatus.EXECUTING)

    response = client.get(f"/api/jobs/{test_job_name}/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == JobStatus.EXECUTING.value
    assert data["id"] == job.id


def test_get_status_finished_job(client, test_job_name, job_config):
    """Test getting status of a finished job."""
    # Create and execute job
    config = job_config(test_job_name)
    job_config_service.create_config(config)
    job = job_service.create_job(test_job_name)

    # Update status to FINISHED with result
    result = {"success": True, "message": "Job completed successfully"}
    job_service.update_job_status(test_job_name, JobStatus.FINISHED, result)

    response = client.get(f"/api/jobs/{test_job_name}/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == JobStatus.FINISHED.value
    assert data["result"] == result
    assert data["id"] == job.id


def test_get_status_failed_job(client, test_job_name, job_config):
    """Test getting status of a failed job."""
    # Create and execute job
    config = job_config(test_job_name)
    job_config_service.create_config(config)
    job = job_service.create_job(test_job_name)

    # Update status to FAILED with error
    error = {"error": "Test error message"}
    job_service.update_job_status(test_job_name, JobStatus.FAILED, error)

    response = client.get(f"/api/jobs/{test_job_name}/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == JobStatus.FAILED.value
    assert "error" in data["result"]
    assert data["id"] == job.id


def test_get_status_cancelled_job(client, test_job_name, job_config):
    """Test getting status of a cancelled job."""
    # Create and execute job
    config = job_config(test_job_name)
    job_config_service.create_config(config)
    job = job_service.create_job(test_job_name)

    # Update status to CANCELLED
    job_service.update_job_status(test_job_name, JobStatus.CANCELLED)

    response = client.get(f"/api/jobs/{test_job_name}/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == JobStatus.CANCELLED.value
    assert data["id"] == job.id
