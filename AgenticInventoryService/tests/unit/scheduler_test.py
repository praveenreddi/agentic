import unittest
from unittest.mock import Mock, patch, AsyncMock
from agentic_inventory.backend.jobs.scheduler import JobScheduler
from agentic_inventory.backend.models.job_config_model import JobConfig
from agentic_inventory.backend.jobs.service import job_config_service
import pytest


@pytest.mark.asyncio
class TestJobScheduler(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.scheduler = JobScheduler()
        self.job_name = "test_job"

        # Create sample job config
        self.sample_job_config = JobConfig(
            id=self.job_name,
            job_name=self.job_name,
            description="Test job",
            schedule="0 0 * * *",
            timeout=60,
            retry_count=1,
            retry_delay=5,
            parameters={"test_param": "test_value"},
        )

    async def test_parse_schedule_predefined(self):
        """Test parsing predefined schedules"""
        # Test hourly schedule
        hourly_params = self.scheduler._parse_schedule("hourly")
        self.assertEqual(hourly_params["minute"], "0")
        self.assertEqual(hourly_params["hour"], "*")

        # Test daily schedule
        daily_params = self.scheduler._parse_schedule("daily")
        self.assertEqual(daily_params["minute"], "0")
        self.assertEqual(daily_params["hour"], "0")

        # Test weekly schedule
        weekly_params = self.scheduler._parse_schedule("weekly")
        self.assertEqual(weekly_params["minute"], "0")
        self.assertEqual(weekly_params["hour"], "0")
        self.assertEqual(weekly_params["day_of_week"], "0")

        # Test monthly schedule
        monthly_params = self.scheduler._parse_schedule("monthly")
        self.assertEqual(monthly_params["minute"], "0")
        self.assertEqual(monthly_params["hour"], "0")
        self.assertEqual(monthly_params["day"], "1")

    def test_parse_schedule_cron_expression(self):
        """Test parsing cron expressions"""
        # Test valid cron expression
        cron_params = self.scheduler._parse_schedule("0 0 * * *")
        self.assertEqual(cron_params["minute"], "0")
        self.assertEqual(cron_params["hour"], "0")
        self.assertEqual(cron_params["day"], "*")
        self.assertEqual(cron_params["month"], "*")
        self.assertEqual(cron_params["day_of_week"], "*")

        # Test invalid cron expression
        with self.assertRaises(ValueError):
            self.scheduler._parse_schedule("invalid_cron")

    async def test_execute_job_wrapper_success(self):
        """Test successful job execution wrapper"""
        # Mock job execution
        mock_execution = AsyncMock()
        mock_execution.return_value = "Job completed successfully"

        # Mock storage
        self.scheduler.storage = Mock()
        self.scheduler.storage.create_job_execution = AsyncMock()
        self.scheduler.storage.update_job_execution = AsyncMock()

        # Execute job wrapper
        await self.scheduler.execute_job_wrapper(self.job_name, self.sample_job_config.model_dump())

        # Verify storage calls
        self.scheduler.storage.create_job_execution.assert_called_once()
        self.scheduler.storage.update_job_execution.assert_called_once()

    async def test_execute_job_wrapper_failure(self):
        """Test job execution wrapper with failure"""
        # Mock job execution to raise an exception
        mock_execution = AsyncMock()
        mock_execution.side_effect = Exception("Job failed")

        # Mock storage
        self.scheduler.storage = Mock()
        self.scheduler.storage.create_job_execution = AsyncMock()
        self.scheduler.storage.update_job_execution = AsyncMock()

        # Execute job wrapper
        await self.scheduler.execute_job_wrapper(self.job_name, self.sample_job_config.model_dump())

        # Verify storage calls
        self.scheduler.storage.create_job_execution.assert_called_once()
        self.scheduler.storage.update_job_execution.assert_called_once()

    async def test_execute_job_wrapper_no_execution(self):
        """Test job execution wrapper with no execution"""
        # Mock storage
        self.scheduler.storage = Mock()
        self.scheduler.storage.create_job_execution = AsyncMock()
        self.scheduler.storage.update_job_execution = AsyncMock()

        # Execute job wrapper with invalid job
        await self.scheduler.execute_job_wrapper("invalid_job", {})

        # Verify storage calls
        self.scheduler.storage.create_job_execution.assert_called_once()
        self.scheduler.storage.update_job_execution.assert_called_once()

    async def test_handle_missed_job(self):
        """Test handling of missed job"""
        # Mock storage
        self.scheduler.storage = Mock()
        self.scheduler.storage.get_job_executions = AsyncMock()
        self.scheduler.storage.update_job_execution = AsyncMock()

        # Set up mock execution
        mock_execution = {
            "id": "test_execution",
            "jobName": self.job_name,
            "status": "QUEUED",
            "result": None,
            "start_time": "2024-03-27T00:00:00Z",
            "end_time": None,
        }
        self.scheduler.storage.get_job_executions.return_value = [mock_execution]

        # Handle missed job
        await self.scheduler._handle_missed_job(Mock(job_id=f"job_{self.job_name}"))

        # Verify storage calls
        self.scheduler.storage.get_job_executions.assert_called_once_with(self.job_name, limit=1)
        self.scheduler.storage.update_job_execution.assert_called_once()

    async def test_schedule_jobs(self):
        """Test scheduling jobs"""
        # Mock job config service
        with patch.object(job_config_service, "list_configs", return_value=[self.sample_job_config]):
            # Schedule jobs
            await self.scheduler.schedule_jobs()

            # Verify job was scheduled
            self.assertEqual(len(self.scheduler.scheduler.get_jobs()), 1)
            self.assertEqual(self.scheduler.scheduler.get_jobs()[0].id, self.job_name)

    async def test_start_scheduler(self):
        """Test starting the scheduler"""
        # Start scheduler
        await self.scheduler.start()

        # Verify scheduler is running
        self.assertTrue(self.scheduler.scheduler.running)

        # Stop scheduler
        self.scheduler.stop()


if __name__ == "__main__":
    unittest.main()
