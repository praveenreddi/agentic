from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_MISSED
from agentic_inventory.utils.extensions import logger
from agentic_inventory.backend.jobs.service import execute_job
from agentic_inventory.backend.models.job_model import JobStatus
from agentic_inventory.backend.storage.storage_jobs import StorageJobsClient
from agentic_inventory.backend.jobs.service import JobConfigService
from agentic_inventory.backend.models.job_execution_model import JobExecutionModel
from datetime import datetime, UTC


_storage_client = StorageJobsClient()
job_config_service = JobConfigService()


class JobScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler(
            timezone="UTC",
            job_defaults={
                "coalesce": True,  # Combine multiple missed runs into a single run
                "max_instances": 1,  # Only allow one instance of each job to run at a time
                "misfire_grace_time": 60,  # Allow jobs to be missed by up to 60 seconds
            },
        )
        # Add listener for missed jobs
        self.scheduler.add_listener(self._handle_missed_job, EVENT_JOB_MISSED)

    def _parse_schedule(self, schedule: str) -> dict:
        """Convert schedule string to cron parameters"""
        schedule_map = {
            "hourly": "0 * * * *",
            "daily": "0 0 * * *",
            "weekly": "0 0 * * 0",
            "monthly": "0 0 1 * *",
        }

        # Handle predefined schedules
        if schedule in schedule_map:
            schedule = schedule_map[schedule]

        # Try to parse as cron expression
        try:
            parts = schedule.split()
            if len(parts) != 5:
                raise ValueError("Invalid cron expression")
            return {"minute": parts[0], "hour": parts[1], "day": parts[2], "month": parts[3], "day_of_week": parts[4]}
        except Exception:
            raise ValueError(f"Invalid cron expression: {schedule}")

    async def execute_job_wrapper(self, job_name: str, job_config: dict):
        """Execute a job and update its status."""
        try:
            # Check if job config exists
            config = _storage_client.get_job_config(job_name)
            if not config:
                raise ValueError(f"Job configuration not found: {job_name}")

            # Create a new execution
            execution = JobExecutionModel(
                id=f"{job_name}_{datetime.now(UTC).isoformat()}",
                job_name=job_name,
                status=JobStatus.QUEUED.value,
                start_time=datetime.now(UTC),
                createdAt=datetime.now(UTC),
                updatedAt=datetime.now(UTC),
                end_time=None,
                result=None,
            )
            _storage_client.create_job_execution(execution)

            # Update status to executing
            execution.status = JobStatus.EXECUTING.value
            _storage_client.update_job_execution(execution)

            # Execute the job
            result = await execute_job(job_name, job_config)

            # Update status to finished with result
            execution.status = JobStatus.FINISHED.value
            execution.result = {"success": True, "data": result}
            execution.end_time = datetime.now(UTC)
            execution.updatedAt = datetime.now(UTC)
            _storage_client.update_job_execution(execution)

        except Exception as e:
            logger.error(f"Error executing job {job_name}: {str(e)}")
            # Update status to failed
            execution = JobExecutionModel(
                id=f"{job_name}_{datetime.now(UTC).isoformat()}",
                job_name=job_name,
                status=JobStatus.FAILED.value,
                start_time=datetime.now(UTC),
                createdAt=datetime.now(UTC),
                updatedAt=datetime.now(UTC),
                end_time=datetime.now(UTC),
                result={"success": False, "error": str(e)},
            )
            _storage_client.create_job_execution(execution)

    def _handle_missed_job(self, event):
        """Handle missed job executions.

        Args:
            event: APScheduler event containing job_id and other event information

        The job_id in the event is the same as the job name we used when scheduling,
        so we can use it directly without any string manipulation.
        """
        logger.warning(f"Job {event.job_id} was missed!")

        try:
            # Create execution record for missed job
            execution = JobExecutionModel(
                id=f"{event.job_id}_{datetime.now(UTC).isoformat()}",
                job_name=event.job_id,
                status=JobStatus.FAILED.value,
                start_time=datetime.now(UTC),
                createdAt=datetime.now(UTC),
                updatedAt=datetime.now(UTC),
                end_time=datetime.now(UTC),
                result={"success": False, "error": "Job was missed due to system being down or overloaded"},
            )
            _storage_client.create_job_execution(execution)
        except Exception as e:
            logger.error(f"Failed to update status for missed job {event.job_id}: {str(e)}")

    def schedule_jobs(self):
        """Schedule all jobs from configuration"""
        # Get all job configs from Cosmos
        job_configs = job_config_service.list_configs()

        for config in job_configs:
            job_name = config.job_name
            try:
                # Parse schedule into cron parameters
                cron_params = self._parse_schedule(config.schedule)

                # Get jitter from config
                jitter = config.jitter

                logger.info(f"Scheduling job {job_name} with cron parameters: {cron_params}, jitter: {jitter}")

                # Schedule the job
                self.scheduler.add_job(
                    self.execute_job_wrapper,
                    CronTrigger(**cron_params),
                    id=job_name,
                    args=[job_name, config.model_dump()],
                    jitter=jitter,  # Add random jitter to job execution time
                )
            except Exception as e:
                logger.error(f"Error scheduling job {job_name}: {str(e)}")

    async def start(self):
        """Start the scheduler"""
        self.scheduler.start()
        logger.info("Job scheduler started")

    def stop(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("Job scheduler stopped")

    def shutdown(self):
        """Stop the scheduler and all running jobs"""
        try:
            if self.scheduler.running:
                self.scheduler.shutdown()
                logger.info("Job scheduler stopped successfully")
            else:
                logger.warning("Scheduler is not running")
        except Exception as e:
            logger.error(f"Failed to stop scheduler: {str(e)}", exc_info=True)
            return


# Global scheduler instance
scheduler = JobScheduler()
