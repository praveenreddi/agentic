"""
Unified Cosmos DB client for the Agentic Inventory Service.

This module provides a centralized interface for all Azure Cosmos DB operations,
including user sessions, session messages, job configurations, and job executions.
"""

from typing import List, Optional
from datetime import datetime

from agentic_inventory.backend.storage.storage import get_storage_client
from agentic_inventory.backend.models.job_execution_model import JobExecutionModel
from agentic_inventory.backend.models.job_config_model import JobConfig
from agentic_inventory.utils.extensions import logger
from agentic_inventory.utils.measure import measure_ts
from azure.cosmos.exceptions import CosmosHttpResponseError


class StorageJobsClient:
    """Repository for storing and retrieving data in Cosmos DB"""

    def __init__(self):
        storage_client = get_storage_client()
        self.job_executions_container = storage_client.job_executions_container
        self.job_configs_container = storage_client.job_configs_container

    @measure_ts
    def get_job_executions(self, job_name: str, limit: int = 10) -> List[JobExecutionModel]:
        """Get job executions for a specific job"""
        try:
            logger.info(f"Getting job executions for job: {job_name}")
            query = "SELECT * FROM c WHERE c.job_name = @job_name ORDER BY c._ts DESC"
            params = [{"name": "@job_name", "value": job_name}]

            items = list(
                self.job_executions_container.query_items(
                    query=query, parameters=params, enable_cross_partition_query=True, max_item_count=limit
                )
            )

            executions = [JobExecutionModel.model_validate(item) for item in items]
            logger.info(f"Found {len(executions)} job executions for job: {job_name}")
            return executions
        except CosmosHttpResponseError as e:
            logger.error(f"Failed to get job executions: {e}")
            logger.error(f"Error details: {e.message}")
            raise

    @measure_ts
    def create_job_execution(self, execution: JobExecutionModel) -> JobExecutionModel:
        """Create a new job execution"""
        try:
            logger.info(f"Creating job execution: {execution}")
            if isinstance(execution, dict):
                job_name = execution["job_name"]
                body = execution
            else:
                job_name = execution.job_name
                body = execution.model_dump()

            # Convert datetime objects to ISO format strings
            datetime_fields = ["createdAt", "updatedAt", "start_time", "end_time"]

            for field in datetime_fields:
                if field in body and isinstance(body[field], datetime):
                    body[field] = body[field].isoformat()

            # Handle nested datetime objects in config
            if "config" in body and isinstance(body["config"], dict):
                config_datetime_fields = ["created_at", "updated_at"]
                for field in config_datetime_fields:
                    if field in body["config"] and isinstance(body["config"][field], datetime):
                        body["config"][field] = body["config"][field].isoformat()

            body["partitionKey"] = job_name
            result = self.job_executions_container.create_item(
                body=body, headers={"x-ms-documentdb-partitionkey": f'["{job_name}"]'}
            )
            logger.info(f"Created job execution: {result}")
            return JobExecutionModel.model_validate(result)
        except CosmosHttpResponseError as e:
            logger.error(f"Failed to create job execution: {e}")
            logger.error(f"Error details: {e.message}")
            raise

    @measure_ts
    def update_job_execution(self, execution: JobExecutionModel) -> JobExecutionModel:
        """Update an existing job execution"""
        try:
            logger.info(f"Updating job execution: {execution}")
            if isinstance(execution, dict):
                job_name = execution["job_name"]
                body = execution
            else:
                job_name = execution.job_name
                body = execution.model_dump()

            # Convert datetime objects to ISO format strings
            datetime_fields = ["createdAt", "updatedAt", "start_time", "end_time"]

            for field in datetime_fields:
                if field in body and isinstance(body[field], datetime):
                    body[field] = body[field].isoformat()

            # Handle nested datetime objects in config
            if "config" in body and isinstance(body["config"], dict):
                config_datetime_fields = ["created_at", "updated_at"]
                for field in config_datetime_fields:
                    if field in body["config"] and isinstance(body["config"][field], datetime):
                        body["config"][field] = body["config"][field].isoformat()

            body["partitionKey"] = job_name
            result = self.job_executions_container.replace_item(
                item=body["id"], body=body, headers={"x-ms-documentdb-partitionkey": f'["{job_name}"]'}
            )
            logger.info(f"Updated job execution: {result}")
            return JobExecutionModel.model_validate(result)
        except CosmosHttpResponseError as e:
            logger.error(f"Failed to update job execution: {e}")
            logger.error(f"Error details: {e.message}")
            raise

    @measure_ts
    def get_job_config(self, name: str) -> Optional[JobConfig]:
        """Get a job configuration by name."""
        logger.info(f"Getting job config for {name}")
        try:
            result = self.job_configs_container.read_item(
                item=name, partition_key=name, headers={"x-ms-documentdb-partitionkey": f'["{name}"]'}
            )
            logger.info(f"Job config retrieved successfully: {result}")
            return JobConfig.model_validate(result)
        except CosmosHttpResponseError as e:
            if e.status_code == 404:
                logger.error(f"Job config {name} not found")
                return None
            logger.error(f"Failed to get job config {name}: {e}")
            raise

    @measure_ts
    def create_job_config(self, config: JobConfig) -> JobConfig:
        """Create a new job configuration"""
        try:
            logger.info(f"Creating job config for {config.job_name}")
            logger.info(f"Config data: {config.model_dump()}")
            result = self.job_configs_container.create_item(
                body=config.model_dump(), headers={"x-ms-documentdb-partitionkey": f'["{config.job_name}"]'}
            )
            logger.info(f"Job config created successfully: {result}")
            return JobConfig.model_validate(result)
        except CosmosHttpResponseError as e:
            logger.error(f"Failed to create job config: {e}")
            logger.error(f"Error details: {e.message}")
            raise

    @measure_ts
    def update_job_config(self, config: JobConfig) -> JobConfig:
        """Update an existing job configuration"""
        try:
            result = self.job_configs_container.replace_item(
                item=config.job_name,
                body=config.model_dump(),
                headers={"x-ms-documentdb-partitionkey": f'["{config.job_name}"]'},
            )
            return JobConfig.model_validate(result)
        except CosmosHttpResponseError as e:
            logger.error(f"Failed to update job config: {e}")
            raise

    @measure_ts
    def delete_job_config(self, name: str) -> None:
        """Delete a job configuration"""
        try:
            self.job_configs_container.delete_item(item=name, headers={"x-ms-documentdb-partitionkey": f'["{name}"]'})
        except CosmosHttpResponseError as e:
            logger.error(f"Failed to delete job config: {e}")
            raise

    @measure_ts
    def list_job_configs(self) -> List[JobConfig]:
        """List all job configurations"""
        try:
            query = "SELECT * FROM c"
            results = list(
                self.job_configs_container.query_items(
                    query=query,
                    enable_cross_partition_query=True,
                )
            )
            return [JobConfig.model_validate(item) for item in results]
        except Exception as e:
            logger.error(f"Failed to list job configs: {str(e)}")
            raise
