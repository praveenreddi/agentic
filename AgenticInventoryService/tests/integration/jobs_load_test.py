import asyncio

from datetime import datetime
from typing import List, Dict
import logging
import uuid
import os
from fastapi.testclient import TestClient
from agentic_inventory.main import app
from agentic_inventory.backend.models.job_config_model import JobConfig
from agentic_inventory.backend.models.notify_config_model import NotifyConfig
from agentic_inventory.backend.models.job_model import JobStatus
from agentic_inventory.backend.jobs.scheduler import scheduler
from agentic_inventory.backend.jobs.service import job_service, job_config_service

# Ensure the log file path is absolute
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "load_test.log")

# Configure root logger
logging.basicConfig(level=logging.INFO)

# Create a custom logger
logger = logging.getLogger("load_test")
logger.setLevel(logging.INFO)

# Create handlers
console_handler = logging.StreamHandler()
file_handler = logging.FileHandler(log_file, mode="w")  # 'w' mode to start fresh each time

# Create formatters and add it to handlers
log_format = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
console_handler.setFormatter(log_format)
file_handler.setFormatter(log_format)

# Add handlers to the logger
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# Disable other loggers to avoid noise
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("fastapi").setLevel(logging.WARNING)


class JobLoadTester:
    def __init__(self):
        logger.info("Initializing JobLoadTester")
        self.client = TestClient(app)
        self.job_results: List[Dict] = []
        self.start_time = None
        self.end_time = None
        self.test_run_id = str(uuid.uuid4())[:8]  # Generate unique ID for this test run
        logger.info(f"Test run ID: {self.test_run_id}")

    async def cleanup_existing_jobs(self):
        """Clean up any existing job configs from previous test runs."""
        try:
            # Get all job configs
            configs = job_config_service.list_configs()
            for config in configs:
                if config.job_name.startswith("load_test_"):
                    logger.info(f"Deleting existing job config: {config.job_name}")
                    job_config_service.delete_config(config.job_name)
            logger.info("Cleanup of existing job configs completed")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}", exc_info=True)

    def create_job_config(self, job_name: str, delay: int = 0) -> JobConfig:
        """Create a job configuration with specified delay."""
        logger.info(f"Creating job config for {job_name} with {delay} second delay")
        return JobConfig(
            id=job_name,  # Set the ID field explicitly
            job_name=job_name,
            description=f"Load test job {job_name} with {delay} second delay",
            schedule="0 0 * * *",  # This won't matter as we'll trigger manually
            parameters={"delay": delay, "test_data": f"Load test data for {job_name}"},  # Simulate work with delay
            notify=NotifyConfig(enabled=True, method="email"),
            timeout=300,  # 5 minutes timeout
            retry_count=3,
            retry_delay=60,
        )

    async def run_job(self, job_name: str, delay: int = 0) -> Dict:
        """Run a single job and track its execution."""
        unique_job_name = f"load_test_{self.test_run_id}_{job_name}"
        try:
            logger.info(f"Starting job {unique_job_name} with {delay} second delay")

            # Create job config using the service directly
            job_config = self.create_job_config(unique_job_name, delay)
            job_config_service.create_config(job_config)
            logger.info(f"Successfully created job config {unique_job_name}")

            # Create job execution using the service directly
            job = job_service.create_job(unique_job_name)
            execution_id = job.id  # Use dot notation instead of dictionary access
            logger.info(f"Created job execution {execution_id} for {unique_job_name}")

            # Update job status to EXECUTING
            job_service.update_job_status(unique_job_name, JobStatus.EXECUTING)
            logger.info(f"Updated job {unique_job_name} status to EXECUTING")

            # Simulate job execution with delay
            await asyncio.sleep(delay)

            # Update job status to FINISHED
            result = {"success": True, "message": f"Job {unique_job_name} completed successfully"}
            job_service.update_job_status(unique_job_name, JobStatus.FINISHED, result)
            logger.info(f"Updated job {unique_job_name} status to FINISHED")

            return {
                "job_name": unique_job_name,
                "execution_id": execution_id,
                "status": JobStatus.FINISHED.value,
                "result": result,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error running job {unique_job_name}: {str(e)}", exc_info=True)
            try:
                job_service.update_job_status(unique_job_name, JobStatus.FAILED, {"error": str(e)})
            except Exception as update_error:
                logger.error(f"Failed to update job status to FAILED: {str(update_error)}")
            return {"job_name": unique_job_name, "status": JobStatus.FAILED.value, "error": str(e)}

    async def run_load_test(self):
        """Run the load test with multiple batches of jobs."""
        self.start_time = datetime.now()
        logger.info("Starting load test...")

        try:
            # Clean up existing job configs first
            await self.cleanup_existing_jobs()

            # First batch: 5 concurrent jobs
            logger.info("Starting first batch of 5 concurrent jobs...")
            first_batch = [self.run_job(f"job_{i}", delay=30) for i in range(5)]  # 30 second delay for each job
            logger.info("Waiting for first batch to complete...")
            first_batch_results = await asyncio.gather(*first_batch)
            self.job_results.extend(first_batch_results)
            logger.info("First batch completed")

            # Second batch: 3 more concurrent jobs
            logger.info("Starting second batch of 3 additional jobs...")
            second_batch = [self.run_job(f"job_{i+5}", delay=45) for i in range(3)]  # 45 second delay for each job
            logger.info("Waiting for second batch to complete...")
            second_batch_results = await asyncio.gather(*second_batch)
            self.job_results.extend(second_batch_results)
            logger.info("Second batch completed")

            self.end_time = datetime.now()
            self.print_summary()
        except Exception as e:
            logger.error(f"Error during load test: {str(e)}", exc_info=True)
            raise

    def print_summary(self):
        """Print a summary of the load test results."""
        duration = self.end_time - self.start_time
        logger.info("\n=== Load Test Summary ===")
        logger.info(f"Test Run ID: {self.test_run_id}")
        logger.info(f"Total duration: {duration}")
        logger.info(f"Total jobs: {len(self.job_results)}")

        # Count job statuses
        status_counts = {}
        for result in self.job_results:
            status = result.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        logger.info("\nJob Status Summary:")
        for status, count in status_counts.items():
            logger.info(f"{status}: {count}")

        # Calculate average job duration
        completed_jobs = [r for r in self.job_results if r.get("status") == JobStatus.FINISHED.value]
        if completed_jobs:
            avg_duration = sum(
                (datetime.fromisoformat(r["timestamp"]) - self.start_time).total_seconds() for r in completed_jobs
            ) / len(completed_jobs)
            logger.info(f"\nAverage job duration: {avg_duration:.2f} seconds")

        # Print individual job results
        logger.info("\nIndividual Job Results:")
        for result in self.job_results:
            logger.info(f"Job {result['job_name']}: {result['status']}")
            if result.get("error"):
                logger.error(f"Error in job {result['job_name']}: {result['error']}")


async def main():
    try:
        logger.info("Starting load test main function")
        # Initialize the scheduler
        await scheduler.start()
        logger.info("Scheduler initialized")

        tester = JobLoadTester()
        await tester.run_load_test()
        logger.info("Load test completed successfully")

        # Shutdown the scheduler
        scheduler.scheduler.shutdown()
        logger.info("Scheduler shutdown complete")
    except Exception as e:
        logger.error(f"Load test failed: {str(e)}", exc_info=True)
        raise


if __name__ == "__main__":
    logger.info("Starting load test script")
    asyncio.run(main())
