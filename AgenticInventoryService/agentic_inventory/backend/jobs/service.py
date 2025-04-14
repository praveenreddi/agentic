from datetime import datetime, UTC
from typing import Dict, Optional, Any, List
from agentic_inventory.utils.extensions import logger
from agentic_inventory.backend.models.job_model import JobStatus
from agentic_inventory.backend.storage.storage_jobs import StorageJobsClient
from agentic_inventory.backend.models.job_config_model import JobConfig
from agentic_inventory.backend.models.job_execution_model import JobExecutionModel


_storage_client = StorageJobsClient()


async def execute_job(job_id: str, config: dict):
    """Execute the actual job based on job_id and configuration"""
    # TODO
    logger.info(f"Executing job {job_id}")
    try:
        if job_id == "daily_report":
            return "Daily report generated successfully"
        elif job_id == "weekly_summary":
            return "Weekly summary generated successfully"
        elif job_id == "data_sync":
            return "Data sync completed successfully"
        else:
            raise ValueError(f"Unknown job: {job_id}")
    except Exception as e:
        logger.error(f"Job execution failed for {job_id}: {str(e)}", exc_info=True)
        return {"error": "Job execution failed"}


def update_job_status(job_name: str, status: JobStatus, result: Optional[Any] = None) -> Dict[str, Any]:
    """Update the status of a job execution"""
    # Get the latest job execution
    executions = _storage_client.get_job_executions(job_name)
    if not executions:
        raise ValueError(f"Job execution not found: {job_name}")

    execution = executions[0]
    execution.status = status.value
    execution.end_time = datetime.now(UTC).isoformat()
    execution.updatedAt = datetime.now(UTC).isoformat()

    if result is not None:
        if isinstance(result, dict):
            execution.result = result
        else:
            execution.result = {
                "success": status == JobStatus.FINISHED,
                "data": result if status == JobStatus.FINISHED else None,
                "error": result if status in [JobStatus.CANCELLED, JobStatus.FAILED] else None,
            }

    return _storage_client.update_job_execution(execution.model_dump())


class JobConfigService:
    """Service for managing job configurations"""

    def __init__(self):
        self.storage = _storage_client

    def create_config(self, config: JobConfig) -> JobConfig:
        """Create a new job configuration"""
        return self.storage.create_job_config(config)

    def get_config(self, name: str) -> Optional[JobConfig]:
        """Get a job configuration by name"""
        return self.storage.get_job_config(name)

    def update_config(self, config: JobConfig) -> JobConfig:
        """Update an existing job configuration"""
        return self.storage.update_job_config(config)

    def delete_config(self, name: str) -> None:
        """Delete a job configuration"""
        self.storage.delete_job_config(name)

    def list_configs(self) -> List[JobConfig]:
        """List all job configurations"""
        return self.storage.list_job_configs()

    def validate_config(self, config: JobConfig) -> List[str]:
        """Validate a job configuration"""
        errors = []

        # Validate required fields
        if not config.job_name:
            errors.append("Job name is required")
        if not config.schedule:
            errors.append("Schedule is required")
        if not config.description:
            errors.append("Description is required")

        # Validate numeric fields
        if config.timeout is not None and config.timeout <= 0:
            errors.append("Timeout must be positive")
        if config.retry_count is not None and config.retry_count < 0:
            errors.append("Retry count must be non-negative")
        if config.retry_delay is not None and config.retry_delay < 0:
            errors.append("Retry delay must be non-negative")
        if config.jitter is not None and config.jitter < 0:
            errors.append("Jitter must be non-negative")

        # Validate notification config
        if config.notify:
            if not config.notify.email and not config.notify.webhook:
                errors.append("At least one notification method must be specified")

        return errors


class JobService:
    """Service for managing job execution"""

    def __init__(self):
        self.storage = _storage_client
        self.config_service = JobConfigService()

    def create_job(self, job_name: str) -> Dict[str, Any]:
        """Create a new job execution"""
        try:
            # Get the job configuration
            config = self.config_service.get_config(job_name)
            if not config:
                raise ValueError(f"Job configuration not found: {job_name}")

            # Create job execution record with timestamp in ID
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            execution = JobExecutionModel(
                id=f"{job_name}_{timestamp}",
                job_name=job_name,
                status=JobStatus.QUEUED.value,
                result=None,
                createdAt=datetime.now(UTC),
                updatedAt=datetime.now(UTC),
                config=config.model_dump(),
                start_time=datetime.now(UTC),
                end_time=None,
            )

            return self.storage.create_job_execution(execution)
        except Exception as e:
            logger.error(f"Failed to create job execution for {job_name}: {str(e)}", exc_info=True)
            return {"error": "Failed to create job execution"}

    def update_job_status(self, job_name: str, status: JobStatus, result: Optional[Any] = None) -> Dict[str, Any]:
        """Update the status of a job execution"""
        try:
            # Get the latest job execution
            executions = self.storage.get_job_executions(job_name)

            # If no executions exist, create a new one
            if not executions:
                logger.info(f"No existing executions found for {job_name}, creating new execution")
                timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                execution = JobExecutionModel(
                    id=f"{job_name}_{timestamp}",
                    job_name=job_name,
                    status=status.value,
                    createdAt=datetime.now(UTC),
                    updatedAt=datetime.now(UTC),
                    start_time=datetime.now(UTC),
                    end_time=None,
                )

                if result is not None:
                    if isinstance(result, dict):
                        execution.result = result
                    else:
                        execution.result = {
                            "success": status == JobStatus.FINISHED,
                            "data": result if status == JobStatus.FINISHED else None,
                            "error": result if status in [JobStatus.FAILED, JobStatus.CANCELLED] else None,
                        }

                return self.storage.create_job_execution(execution)

            # Update existing execution
            execution = executions[0]
            execution.status = status.value
            execution.updatedAt = datetime.now(UTC)

            # Only update end_time for terminal states
            if status in [JobStatus.FINISHED, JobStatus.FAILED, JobStatus.CANCELLED]:
                execution.end_time = datetime.now(UTC)

            if result is not None:
                if isinstance(result, dict):
                    execution.result = result
                else:
                    execution.result = {
                        "success": status == JobStatus.FINISHED,
                        "data": result if status == JobStatus.FINISHED else None,
                        "error": result if status in [JobStatus.FAILED, JobStatus.CANCELLED] else None,
                    }

            return self.storage.update_job_execution(execution)
        except Exception as e:
            logger.error(f"Failed to update job status for {job_name}: {str(e)}", exc_info=True)
            return {"error": "Failed to update job status"}


# Global service instances
job_config_service = JobConfigService()
job_service = JobService()
