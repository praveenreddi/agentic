"""
Unified Cosmos DB client for the Agentic Inventory Service.

This module provides a centralized interface for all Azure Cosmos DB operations,
including user sessions, session messages, job configurations, and job executions.
"""

from azure.cosmos import CosmosClient, PartitionKey, exceptions as cosmos_exceptions

from agentic_inventory.utils import config
from agentic_inventory.utils.extensions import logger


def get_storage_client() -> "StorageClient":
    """Get a StorageClient instance (singleton pattern)."""
    return StorageClient.get_instance()


class StorageClient:
    """Repository for storing and retrieving data in Cosmos DB.

    This unified repository handles all cosmos DB operations including:
    - User sessions
    - Session messages
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        """Create a new instance if one doesn't exist."""
        if cls._instance is None:
            cls._instance = super(StorageClient, cls).__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "StorageClient":
        """Get the singleton instance of StorageClient."""
        if cls._instance is None:
            cls._instance = StorageClient()
        return cls._instance

    def __init__(self):
        """Initialize the storage client with Cosmos DB configuration."""
        if StorageClient._initialized:
            return

        # CosmosDB Configuration
        self.endpoint = config.COSMOSDB_ENDPOINT
        self.database_name = config.COSMOSDB_DATABASE_NAME
        self.default_ttl = config.COSMOSDB_SESSION_TTL

        logger.info(f"Initializing CosmosDB client with endpoint: {self.endpoint}, database: {self.database_name}")

        # Initialize client
        try:
            self.client = CosmosClient(
                url=self.endpoint,
                credential=config.COSMOSDB_ACCOUNT_KEY.get_secret_value(),
                consistency_level=None,
                **{"retry_connect": 3},
            )
            logger.info("CosmosDB client initialized successfully")

            self.database = self._get_or_create_database(self.database_name)
            logger.info("Database initialized successfully")

            # Set up containers
            self.setup_containers()
            logger.info("Containers set up successfully")

            StorageClient._initialized = True
            logger.info("StorageClient initialization completed")
        except Exception as e:
            logger.error(f"Failed to initialize CosmosClient: {str(e)}")
            raise

    def _get_or_create_database(self, database_name: str):
        """Get or create a database.

        Args:
            database_name: The database name

        Returns:
            The database client
        """
        try:
            if self.client is None:
                return None
            client = self.client.get_database_client(database=database_name)
            # validate it is there
            client.read()
            logger.info(f"Reusing database {database_name}")
            return client
        except cosmos_exceptions.CosmosResourceNotFoundError:
            logger.info(f"Creating database {database_name}")
            return self.client.create_database(database_name)
        except Exception as e:
            logger.error(f"Error getting/creating database {database_name}: {str(e)}")
            raise

    def setup_containers(self):
        """Set up Cosmos DB containers with proper configuration."""
        logger.info("Setting up containers...")
        # User Sessions container
        self.user_sessions_container = self._create_container_if_not_exists(
            container_id="UserSessions", partition_key_path="/user_id", default_ttl=self.default_ttl
        )
        logger.info("UserSessions container set up")

        # Session Messages container
        self.session_messages_container = self._create_container_if_not_exists(
            container_id="SessionMessages", partition_key_path="/session_id", default_ttl=self.default_ttl
        )
        logger.info("SessionMessages container set up")

        # Job Executions container
        self.job_executions_container = self._create_container_if_not_exists(
            container_id="JobExecutions", partition_key_path="/job_name"
        )
        logger.info("JobExecutions container set up")

        # Job Configs container
        self.job_configs_container = self._create_container_if_not_exists(
            container_id="JobConfigs", partition_key_path="/job_name"
        )
        logger.info("JobConfigs container set up")

    def _create_container_if_not_exists(self, container_id: str, partition_key_path: str, default_ttl: int = None):
        """Create a container if it doesn't exist.

        Args:
            container_id: The container ID
            partition_key_path: The partition key path
            default_ttl: The default TTL in seconds

        Returns:
            The container client
        """
        try:
            container = self.database.get_container_client(container_id)
            # validate it is there
            container.read()
            logger.info(f"Reusing container {container_id}")
            return container
        except cosmos_exceptions.CosmosResourceNotFoundError:
            logger.info(f"Creating container {container_id}")
            container_params = {
                "id": container_id,
                "partition_key": PartitionKey(path=partition_key_path),
            }
            if default_ttl is not None:
                container_params["default_ttl"] = default_ttl
            return self.database.create_container(**container_params)
        except Exception as e:
            logger.error(f"Error getting/creating container {container_id}: {str(e)}")
            raise


# Create a global instance of StorageClient
# _storage_client = StorageClient.get_instance()

# Export the function and instance
# __all__ = ["StorageClient", "get_storage_client", "_storage_client"]
