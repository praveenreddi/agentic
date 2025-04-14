"""
Shared client initialization for the HGV Agentic Inventory Service.
"""

import json
from google.cloud import bigquery
from google.oauth2 import service_account
from azure.keyvault.secrets import SecretClient
from azure.identity import ClientSecretCredential
from agentic_inventory.utils import config


def init_azure_clients():
    """Initialize Azure clients."""
    credential = ClientSecretCredential(
        tenant_id=config.ML_GCP_TENANT_ID,
        client_id=config.ML_GCP_CLIENT_ID,
        client_secret=config.ML_GCP_CLIENT_SECRET.get_secret_value(),
    )

    vault_url = config.ML_GCP_VAULT_URL
    secret_client = SecretClient(vault_url=vault_url, credential=credential)
    return credential, secret_client


def get_bigquery_client(secret_client):
    """Initialize and return BigQuery client."""
    key = json.loads(secret_client.get_secret(config.KEYFILE).value)
    credentials = service_account.Credentials.from_service_account_info(key, scopes=[config.GCP_QUERY_ENDPOINT])
    return bigquery.Client(credentials=credentials, project=config.GCP_PROJECT_ID)


# Initialize shared clients
_, secret_client = init_azure_clients()
bigquery_client = get_bigquery_client(secret_client)
