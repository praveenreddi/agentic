import asyncio
import pytest
import uuid
from unittest.mock import AsyncMock, patch
from agentic_inventory.backend.storage.storage_jobs import StorageJobsClient

# Mock the storage client before importing any modules that use it
mock_storage = AsyncMock(spec=StorageJobsClient)
with patch("agentic_inventory.backend.storage.storage.get_storage_client", mock_storage):
    from agentic_inventory.backend.jobs.scheduler import JobScheduler
    from agentic_inventory.backend.models.job_config_model import JobConfig
    from agentic_inventory.backend.models.job_execution_model import JobExecutionModel
    from agentic_inventory.backend.models.job_model import JobStatus


@pytest.fixture
def job_name():
    """Generate a unique job name for testing"""
    return f"test_integration_{uuid.uuid4()}"


@pytest.fixture
def job_config(job_name):
    """Create a test job configuration"""
    return JobConfig(
        id=job_name,
        job_name=job_name,
        description="Test job configuration",
        schedule="0 * * * *",  # Run at the start of every hour
        enabled=True,
        timeout=3600,
        retry_count=3,
        retry_delay=300,
    )


@pytest.fixture
async def setup_scheduler(job_config):
    """Set up a test scheduler with mock storage"""
    scheduler = JobScheduler(mock_storage)
    scheduler.job_name = job_config.job_name
    scheduler.job_config = job_config.model_dump()
    return scheduler


@pytest.mark.asyncio
async def test_job_scheduling_and_execution(setup_scheduler):
    """Test the complete job scheduling and execution flow."""
    test_scheduler = await setup_scheduler

    # Set up mock for list_configs
    mock_storage.list_job_configs.return_value = [test_scheduler.job_config]
    mock_storage.get_job_config.return_value = test_scheduler.job_config

    # Start the scheduler
    await test_scheduler.start()

    # Schedule the test job
    await test_scheduler.schedule_jobs()

    # Verify the job was scheduled
    jobs = test_scheduler.scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == test_scheduler.job_name

    # Set up mock execution result
    execution = JobExecutionModel(
        id=str(uuid.uuid4()),
        jobjob_name=test_scheduler.job_name,
        status=JobStatus.FINISHED,
        result={"success": True},
    )
    mock_storage.create_job_execution.return_value = execution.model_dump()
    mock_storage.get_job_executions.return_value = [execution.model_dump()]
    mock_storage.update_job_execution.return_value = execution.model_dump()

    # Trigger the job execution immediately
    await test_scheduler.execute_job_wrapper(test_scheduler.job_name, test_scheduler.job_config)

    # Verify job execution details
    executions = await mock_storage.get_job_executions(test_scheduler.job_name, limit=1)
    assert len(executions) == 1
    assert executions[0]["status"] == JobStatus.FINISHED
    assert executions[0]["result"] == {"success": True}

    # Stop the scheduler
    await test_scheduler.stop()


@pytest.mark.asyncio
async def test_missed_job_handling(setup_scheduler):
    """Test handling of missed job executions."""
    test_scheduler = await setup_scheduler

    # Create a job execution that will be marked as missed
    execution = JobExecutionModel(
        id=str(uuid.uuid4()),
        jobjob_name=test_scheduler.job_name,
        status=JobStatus.QUEUED,
        result=None,
    )
    mock_storage.create_job_execution.return_value = execution.model_dump()
    mock_storage.get_job_executions.return_value = [execution.model_dump()]
    mock_storage.get_job_config.return_value = test_scheduler.job_config

    # Create a job that will be missed
    await mock_storage.create_job_execution(execution.model_dump())

    # Wait a bit to ensure the job is considered missed
    await asyncio.sleep(5)

    # Set up mock for missed job handling
    missed_execution = JobExecutionModel(
        id=execution.id,
        jobjob_name=execution.job_name,
        status=JobStatus.FAILED,
        result={"error": "Job execution was missed"},
    )
    mock_storage.get_job_executions.return_value = [missed_execution.model_dump()]
    mock_storage.update_job_execution.return_value = missed_execution.model_dump()

    # Trigger missed job handling
    await test_scheduler._handle_missed_job(type("Event", (), {"job_id": f"job_{test_scheduler.job_name}"})())

    # Verify the missed job was marked as failed
    executions = await mock_storage.get_job_executions(test_scheduler.job_name, limit=1)
    assert len(executions) == 1
    assert executions[0]["status"] == JobStatus.FAILED
    assert executions[0]["result"] == {"error": "Job execution was missed"}


@pytest.mark.asyncio
async def test_job_cancellation(setup_scheduler):
    """Test cancelling a running job."""
    test_scheduler = await setup_scheduler

    # Create a job execution that will be cancelled
    execution = JobExecutionModel(
        id=str(uuid.uuid4()),
        jobjob_name=test_scheduler.job_name,
        status=JobStatus.QUEUED,
        result=None,
    )
    mock_storage.create_job_execution.return_value = execution.model_dump()
    mock_storage.get_job_executions.return_value = [execution.model_dump()]
    mock_storage.get_job_config.return_value = test_scheduler.job_config

    # Create a job that will be cancelled
    await mock_storage.create_job_execution(execution.model_dump())

    # Update job status to EXECUTING
    executing_execution = JobExecutionModel(
        id=execution.id,
        jobjob_name=execution.job_name,
        status=JobStatus.EXECUTING,
        result=None,
    )
    mock_storage.update_job_execution.return_value = executing_execution.model_dump()
    await mock_storage.update_job_execution(executing_execution.model_dump())

    # Cancel the job
    cancelled_execution = JobExecutionModel(
        id=execution.id,
        jobjob_name=execution.job_name,
        status=JobStatus.CANCELLED,
        result={"message": "Job was cancelled"},
    )
    mock_storage.update_job_execution.return_value = cancelled_execution.model_dump()
    await mock_storage.update_job_execution(cancelled_execution.model_dump())

    # Verify the job was cancelled
    executions = await mock_storage.get_job_executions(test_scheduler.job_name, limit=1)
    assert len(executions) == 1
    assert executions[0]["status"] == JobStatus.CANCELLED
    assert executions[0]["result"] == {"message": "Job was cancelled"}
