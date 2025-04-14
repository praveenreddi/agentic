"""
Configuration settings for the HGV Framework API.
"""

import os
from base64 import b64encode
from dotenv import load_dotenv
from pydantic import SecretStr

# Load environment variables from .env file
load_dotenv()

# Server settings
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", 8080))
LOG_LEVEL = str(os.environ.get("LOG_LEVEL", "INFO"))
PLAIN_LOGS = bool(os.environ.get("PLAIN_LOGS", "false").lower() == "true")
MEASURE_LATENCY = bool(os.environ.get("MEASURE_LATENCY", "True").lower() == "true")

APPLICATIONINSIGHTS_CONNECTION_STRING = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "")

# API Configuration
API_TITLE = "HGV Agentic Inventory Service"
API_DESCRIPTION = "API for the HGV Agentic Inventory Service"
API_VERSION = "1.0.0"
FRAMEWORK_NAME = "HGV Agentic Framework"

# CORS settings
CORS_ORIGINS = ["*"]
CORS_ALLOW_CREDENTIALS = True

# Azure OpenAI Settings
LLM_TEMPERATURE = os.getenv("LLM_TEMPERATURE", 0.0)
LLM_TOP_P = os.getenv("LLM_TOP_P", 1.0)

AZURE_OPENAI_ACCOUNT = str(os.environ.get("AZURE_OPENAI_ACCOUNT"))
AZURE_OPENAI_API_KEY = SecretStr(secret_value=str(os.environ.get("AZURE_OPENAI_API_KEY")))
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
# CAUTION: This must be set manually to True for the case when you need to deploy things
AZURE_OPENAI_DEPLOY = bool(os.getenv("AZURE_OPENAI_DEPLOY", "false").lower() == "true")
# these are RG/SubId of Azure OpenAI account and not container app
AZURE_OPENAI_RESOURCE_GROUP = str(os.environ.get("AZURE_OPENAI_RESOURCE_GROUP"))
AZURE_OPENAI_SUBSCRIPTION_ID = str(os.environ.get("AZURE_OPENAI_SUBSCRIPTION_ID"))
AZURE_OPENAI_CAPACITY = int(os.environ.get("AZURE_OPENAI_CAPACITY", 100))
AZURE_OPENAI_API_VERSION = str(os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"))
AZURE_OPENAI_DEPLOYMENT_NAME = str(os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "ai-inventory"))
AZURE_OPENAI_MODEL_NAME = str(os.environ.get("AZURE_OPENAI_MODEL_NAME", "gpt-4o"))
AZURE_OPENAI_MODEL_VERSION = str(os.environ.get("AZURE_OPENAI_MODEL_VERSION", "2024-11-20"))

# ollama config
LLM_PROVIDER = str(os.environ.get("LLM_PROVIDER", "azure"))
OLLMA_BASE_URL = str(os.environ.get("OLLMA_BASE_URL", ""))
OLLAMA_MODEL_NAME = str(os.environ.get("OLLAMA_MODEL_NAME", "llama3.1"))

# Azure Authentication Settings
# TODO Undo all this mess
ML_GCP_TENANT_ID = os.getenv("ML_GCP_TENANT_ID", "1a0105b6-f4af-42cf-895d-25550fe6bd5a")
ML_GCP_CLIENT_ID = os.getenv("ML_GCP_CLIENT_ID", "6523f29e-0ee3-406c-acda-a3426589f5b0")
ML_GCP_CLIENT_SECRET = SecretStr(secret_value=str(os.environ.get("ML_GCP_CLIENT_SECRET")))
ML_GCP_VAULT_URL = os.getenv("ML_GCP_VAULTURL", "https://donemsft01e2ml5061159626.vault.azure.net/")

# GCP Settings
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "dri-it-prod-hgv")
GCP_QUERY_ENDPOINT = os.getenv("GCP_QUERY_ENDPOINT", "https://www.googleapis.com/auth/cloud-platform")
KEYFILE = os.getenv("KEYFILE", "bigquery-keyfile")

# ML Settings
ML_TOKEN = SecretStr(secret_value=str(os.environ.get("ML_TOKEN")))
ML_URL = os.getenv("ML_URL")

# HGV API Configurations
HGV_BASE_URL = os.getenv("HGV_BASE_URL", "https://api.dev.onegrandvacation.com")
HGV_SUBSCRIPTION_KEY = os.getenv("HGV_SUBSCRIPTION_KEY")

# this are new and not dependant
HGV_LOOKUP_PATH = "/recommendation-service/v2/properties/lookup"
HGV_AVAIL_PATH = "/recommendation-service/v2/properties/availability"

# Cosmos DB Configuration
COSMOSDB_ENDPOINT = os.getenv("COSMOSDB_ENDPOINT", "")
COSMOSDB_DATABASE_NAME = os.getenv("COSMOSDB_DATABASE_NAME", "")
COSMOSDB_ACCOUNT_KEY = SecretStr(secret_value=str(os.environ.get("COSMOSDB_ACCOUNT_KEY")))
COSMOSDB_SESSION_TTL = int(os.getenv("COSMOSDB_SESSION_TTL", 2592000))
COSMOSDB_CONT_SIZE = int(os.getenv("COSMOSDB_CONT_SIZE", 400))

# SSO
SSO_ENABLED = bool(os.getenv("AZURE_OPENAI_DEPLOY", "true").lower() == "true")
SSO_CLIENT_ID = os.getenv("SSO_CLIENT_ID", "6466ee5d-8bd0-4b6d-b381-e78da2a635b4")
SSO_TENANT_ID = os.getenv("SSO_TENANT_ID", "1a0105b6-f4af-42cf-895d-25550fe6bd5a")
HGV_REDIRECT_URL = os.getenv("HGV_REDIRECT_URL", "http://localhost:8080")

APP_MSI_CLIENT_ID = os.environ.get("APP_MSI_CLIENT_ID")
# API Security
API_SECRET = SecretStr(
    secret_value=os.getenv("API_SECRET", b64encode("AllTheYieldAreBelongsToUs".encode("utf-8")).decode("utf-8"))
)
