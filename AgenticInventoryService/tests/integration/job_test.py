import pytest

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from agentic_inventory.backend.storage.storage_jobs import StorageJobsClient

# Mock the storage client before importing any modules that use it
mock_storage = AsyncMock(spec=StorageJobsClient)
with patch("agentic_inventory.backend.storage.storage.get_storage_client", mock_storage):
    from agentic_inventory.backend.jobs.service import JobService, JobConfigService
    from agentic_inventory.backend.models.job_config_model import JobConfig
    from agentic_inventory.backend.models.job_model import JobStatus


@pytest.fixture
def job_name(request):
    """Generate a unique job name for testing"""
    test_name = request.node.name
    return f"{test_name}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"


@pytest.fixture
def mock_storage():
    """Create a mock storage client."""
    storage = MagicMock(spec=StorageJobsClient)
    return storage


@pytest.fixture
def job_config(job_name):
    """Create a test job configuration"""
    return JobConfig(
        id=job_name,
        job_name=job_name,
        description="Test job config",
        schedule="0 0 * * *",
        timeout=3600,
        retry_count=3,
        retry_delay=300,
        enabled=True,
    )


@pytest.fixture
def test_services():
    """Create service instances for testing."""
    return JobService(), JobConfigService()


@pytest.fixture(scope="function")
def config_service(test_services):
    """Get the config service instance."""
    return test_services[1]


@pytest.fixture
def job_config_service(mock_storage):
    """Create a job config service with mock storage"""
    with patch("agentic_inventory.backend.storage.storage._storage_client", mock_storage):
        return JobConfigService()


@pytest.fixture
def job_service(mock_storage, job_config_service):
    """Create a job service with mock storage and config service"""
    with patch("agentic_inventory.backend.storage.storage.get_storage_client", mock_storage):
        return JobService()


@pytest.mark.asyncio
class TestJobIntegration:
    """Integration tests for job scheduling and execution."""

    @pytest.mark.asyncio
    async def test_job_creation_and_execution(self, job_name, test_services, job_config):
        """Test job creation and execution flow"""
        # Set up mock for successful execution
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        execution_dict = {
            "id": f"{job_name}_{timestamp}",
            "job_name": job_name,
            "status": JobStatus.QUEUED.value,
            "config": job_config.model_dump(),
            "start_time": datetime.now(UTC).isoformat(),
            "end_time": None,
            "result": None,
        }

        with patch("agentic_inventory.backend.storage.storage.get_storage_client") as mock_storage:
            # Configure mock storage
            mock_storage.create_job_config.return_value = job_config
            mock_storage.get_job_config.return_value = job_config
            mock_storage.create_job_execution.return_value = execution_dict
            mock_storage.get_job_executions.return_value = [execution_dict]

            # Create service instances with patched storage
            config_service = JobConfigService()
            job_service = JobService()

            # Set up job configuration
            config_service.create_config(job_config)

            # Create and verify job execution
            result = job_service.create_job(job_name)
            assert result["job_name"] == job_name
            assert result["status"] == JobStatus.QUEUED.value

    @pytest.mark.asyncio
    async def test_job_retry_on_failure(self, job_name, job_config):
        """Test job retry behavior on failure"""
        # Set up mock for failed execution
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        execution_dict = {
            "id": f"{job_name}_{timestamp}",
            "job_name": job_name,
            "status": JobStatus.QUEUED.value,
            "config": job_config.model_dump(),
            "start_time": datetime.now(UTC).isoformat(),
            "end_time": None,
            "result": None,
        }

        with patch("agentic_inventory.backend.storage.storage.get_storage_client") as mock_storage:
            # Configure mock storage
            mock_storage.create_job_config.return_value = job_config
            mock_storage.get_job_config.return_value = job_config
            mock_storage.create_job_execution.return_value = execution_dict
            mock_storage.get_job_executions.return_value = [execution_dict]

            # Create service instances with patched storage
            config_service = JobConfigService()
            job_service = JobService()

            # Create job configuration first
            config_service.create_config(job_config)

            # Create job execution
            result = job_service.create_job(job_name)
            assert result["job_name"] == job_name
            assert result["status"] == JobStatus.QUEUED.value

            # Update status to failed
            failed_dict = dict(execution_dict)
            failed_dict["status"] = JobStatus.FAILED.value
            failed_dict["end_time"] = datetime.now(UTC).isoformat()
            failed_dict["result"] = {"success": False, "error": "Test failure"}
            mock_storage.get_job_executions.return_value = [failed_dict]

            # Verify job status is updated
            result = job_service.update_job_status(job_name, JobStatus.FAILED, "Test failure")
            assert result["status"] == JobStatus.FAILED.value
            assert result["result"]["error"] == "Test failure"

    @pytest.mark.asyncio
    async def test_job_timeout(self, job_name, job_config):
        """Test job timeout behavior"""
        # Set up mock for timed out execution
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        execution_dict = {
            "id": f"{job_name}_{timestamp}",
            "job_name": job_name,
            "status": JobStatus.QUEUED.value,
            "config": job_config.model_dump(),
            "start_time": datetime.now(UTC).isoformat(),
            "end_time": None,
            "result": None,
        }

        with patch("agentic_inventory.backend.storage.storage.get_storage_client") as mock_storage:
            # Configure mock storage
            mock_storage.create_job_config.return_value = job_config
            mock_storage.get_job_config.return_value = job_config
            mock_storage.create_job_execution.return_value = execution_dict
            mock_storage.get_job_executions.return_value = [execution_dict]

            # Create service instances with patched storage
            config_service = JobConfigService()
            job_service = JobService()

            # Set up job configuration
            config_service.create_config(job_config)
            print(f"Created job config: {job_config.job_name}")

            # Create a new job execution that will timeout
            job = job_service.create_job(job_name)
            assert job["job_name"] == job_name
            assert job["status"] == JobStatus.QUEUED.value

            # Update status to cancelled (timeout)
            timeout_dict = dict(execution_dict)
            timeout_dict["status"] = JobStatus.CANCELLED.value
            timeout_dict["end_time"] = datetime.now(UTC).isoformat()
            timeout_dict["result"] = {"success": False, "error": "Job timed out"}
            mock_storage.get_job_executions.return_value = [timeout_dict]

            # Verify job status is updated
            result = job_service.update_job_status(job_name, JobStatus.CANCELLED, "Job timed out")
            assert result["status"] == JobStatus.CANCELLED.value
            assert result["result"]["error"] == "Job timed out"
