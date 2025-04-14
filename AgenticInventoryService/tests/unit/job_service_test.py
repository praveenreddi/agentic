import unittest
import uuid

from unittest.mock import Mock
from agentic_inventory.backend.jobs.service import JobConfigService, JobService
from agentic_inventory.backend.models.job_config_model import JobConfig
import pytest


@pytest.mark.asyncio
class TestJobService(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.mock_storage = self._create_mock_storage()
        self.config_service = JobConfigService()
        self.config_service.storage = self.mock_storage
        self.job_service = JobService()
        self.job_service.storage = self.mock_storage
        self.job_service.config_service = JobConfigService()
        self.job_service.config_service.storage = self.mock_storage

        # Create sample job configs
        self.job_id = f"test_job_{uuid.uuid4()}"
        self.sample_job_config = JobConfig(
            id=self.job_id,
            job_name=self.job_id,
            description="Test job for unit tests",
            schedule="daily",
            timeout=3600,
            retry_count=3,
            retry_delay=300,
        )

        self.job_id_no_notify = f"test_job_no_notify_{uuid.uuid4()}"
        self.sample_job_config_no_notify = JobConfig(
            id=self.job_id_no_notify,
            job_name=self.job_id_no_notify,
            description="Test job without notifications",
            schedule="daily",
            timeout=3600,
            retry_count=3,
            retry_delay=300,
            parameters={"test_param": "test_value"},
        )

    def _create_mock_storage(self):
        """Create a mock storage client for testing"""
        configs = {}
        executions = {}

        def create_job_config(config):
            configs[config.job_name] = config
            return config

        def get_job_config(name):
            return configs.get(name)

        def update_job_config(config):
            configs[config.job_name] = config
            return config

        def delete_job_config(name):
            if name in configs:
                del configs[name]

        def list_job_configs():
            return list(configs.values())

        def create_job_execution(execution):
            executions[execution["jobName"]] = execution
            return execution

        def get_job_executions(job_name, limit=1):
            if job_name in executions:
                return [executions[job_name]]
            return []

        def update_job_execution(execution):
            executions[execution["jobName"]] = execution
            return execution

        storage = Mock()
        storage.create_job_config = Mock(side_effect=create_job_config)
        storage.get_job_config = Mock(side_effect=get_job_config)
        storage.update_job_config = Mock(side_effect=update_job_config)
        storage.delete_job_config = Mock(side_effect=delete_job_config)
        storage.list_job_configs = Mock(side_effect=list_job_configs)
        storage.create_job_execution = Mock(side_effect=create_job_execution)
        storage.get_job_executions = Mock(side_effect=get_job_executions)
        storage.update_job_execution = Mock(side_effect=update_job_execution)
        return storage

    def tearDown(self):
        """Clean up after each test method."""
        try:
            self.config_service.delete_config(self.sample_job_config.job_name)
            self.config_service.delete_config(self.sample_job_config_no_notify.job_name)
        except Exception:
            pass

    async def test_create_and_load_config(self):
        """Test creating and loading a job configuration"""
        # Create config
        created_config = await self.config_service.create_config(self.sample_job_config)
        self.assertEqual(created_config.job_name, self.sample_job_config.job_name)
        self.assertEqual(created_config.schedule, self.sample_job_config.schedule)

        # Load config
        loaded_config = await self.config_service.get_config(self.sample_job_config.job_name)
        self.assertIsNotNone(loaded_config)
        self.assertEqual(loaded_config.job_name, self.sample_job_config.job_name)
        self.assertEqual(loaded_config.schedule, self.sample_job_config.schedule)

    async def test_update_config(self):
        """Test updating a job configuration"""
        # Create config
        created_config = await self.config_service.create_config(self.sample_job_config)
        self.assertEqual(created_config.job_name, self.sample_job_config.job_name)

        # Update config
        updated_config = await self.config_service.update_config(
            self.sample_job_config.job_name, {"description": "Updated description"}
        )
        self.assertEqual(updated_config.description, "Updated description")

    async def test_delete_config(self):
        """Test deleting a job configuration"""
        # Create config
        created_config = await self.config_service.create_config(self.sample_job_config)
        self.assertEqual(created_config.job_name, self.sample_job_config.job_name)

        # Delete config
        await self.config_service.delete_config(self.sample_job_config.job_name)
        deleted_config = await self.config_service.get_config(self.sample_job_config.job_name)
        self.assertIsNone(deleted_config)

    async def test_validate_config(self):
        """Test job configuration validation."""
        # Test valid config
        valid_config = JobConfig(
            id=f"valid_job_{uuid.uuid4()}",
            job_name="valid_job",
            description="Valid job config",
            schedule="0 0 * * *",
            enabled=True,
        )
        self.assertTrue(self.config_service.validate_config(valid_config))

        # Test invalid config
        invalid_config = JobConfig(
            id=f"invalid_job_{uuid.uuid4()}",
            job_name="",  # Missing name
            schedule="",  # Missing schedule
            enabled=True,
            timeout=-1,  # Invalid timeout
            retry_count=-1,  # Invalid retry count
        )
        self.assertFalse(self.config_service.validate_config(invalid_config))
        self.assertIn("Job name is required", self.config_service.validate_config(invalid_config))
        self.assertIn("Schedule is required", self.config_service.validate_config(invalid_config))
        self.assertIn("Timeout must be positive", self.config_service.validate_config(invalid_config))
        self.assertIn("Retry count must be non-negative", self.config_service.validate_config(invalid_config))

    async def test_list_configs(self):
        """Test listing job configurations."""
        # Create configs
        await self.config_service.create_config(self.sample_job_config)
        await self.config_service.create_config(self.sample_job_config_no_notify)

        # List all configs
        all_configs = await self.config_service.list_configs()
        self.assertGreaterEqual(len(all_configs), 2)

        # Verify configs are in the list
        config_names = [c.job_name for c in all_configs]
        self.assertIn(self.sample_job_config.job_name, config_names)
        self.assertIn(self.sample_job_config_no_notify.job_name, config_names)

        # Clean up
        await self.config_service.delete_config(self.sample_job_config.job_name)
        await self.config_service.delete_config(self.sample_job_config_no_notify.job_name)

    async def test_job_execution(self):
        """Test job execution"""
        # Create job config
        await self.config_service.create_config(self.sample_job_config)

        # Execute job
        result = await self.job_service.execute_job(
            self.sample_job_config.job_name, self.sample_job_config.model_dump()
        )
        self.assertIsNotNone(result)

        # Clean up
        await self.config_service.delete_config(self.sample_job_config.job_name)

    async def test_job_execution_failure(self):
        """Test failed job execution"""
        # Create job config
        await self.config_service.create_config(self.sample_job_config)

        # Execute job with invalid parameters
        with self.assertRaises(Exception):
            await self.job_service.execute_job(self.sample_job_config.job_name, {"invalid": "params"})

        # Clean up
        await self.config_service.delete_config(self.sample_job_config.job_name)

    async def test_job_execution_with_dict_result(self):
        """Test job execution with dictionary result"""
        # Create job config
        await self.config_service.create_config(self.sample_job_config)

        # Execute job
        result = await self.job_service.execute_job(
            self.sample_job_config.job_name, self.sample_job_config.model_dump()
        )
        self.assertIsInstance(result, dict)

        # Clean up
        await self.config_service.delete_config(self.sample_job_config.job_name)


if __name__ == "__main__":
    unittest.main()
