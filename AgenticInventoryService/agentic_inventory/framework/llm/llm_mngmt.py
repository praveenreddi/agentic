from openai import AzureOpenAI
from agentic_inventory.utils import config
from agentic_inventory.utils.extensions import logger
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError

# from ollama import ChatOllama

COGNITIVE_SERVICES_API_VERSION = "2023-05-01"


def _get_credential():
    cred = None
    if config.APP_MSI_CLIENT_ID is not None:
        logger.info("Using ManagedIdentityCredential.")
        cred = ManagedIdentityCredential(client_id=config.APP_MSI_CLIENT_ID)
    else:
        logger.info("Using DefaultAzureCredential")
        cred = DefaultAzureCredential()
    return cred


def _get_cogn_acc():
    return CognitiveServicesManagementClient(
        credential=_get_credential(),
        subscription_id=config.AZURE_OPENAI_SUBSCRIPTION_ID,
        api_version=COGNITIVE_SERVICES_API_VERSION,
    )


class LLMClient:
    """A convenience class to handle LLM setups"""

    _cog_acc: CognitiveServicesManagementClient
    # _llm: AzureOpenAI | ChatOllama
    _llm: AzureOpenAI

    def __init__(self, redeploy: bool = False):
        # dummy for pydantic and lookups. the ENV var is used actually
        self.__api_key = config.AZURE_OPENAI_API_KEY

        if redeploy:
            logger.info("Will check and re-deploy OpenAI")
            self._cog_acc = _get_cogn_acc()
            self._get_or_create_deployments(self._get_deploymnet_cfg())
        else:
            if config.LLM_PROVIDER.lower() == "azure":
                logger.info(f"Will use deployed versions {config.AZURE_OPENAI_DEPLOYMENT_NAME}")
            # elif config.LLM_PROVIDER.lower() == "ollama":
            #     logger.info(f"Will use {config.OLLAMA_MODEL_NAME}")
            else:
                raise ValueError(f"Unsupported LLM_PROVIDER: {config.LLM_PROVIDER}")
        self._llm = self._get_client()

    def get_llm(self):
        """Gets an instance of the LLM"""
        return self._llm

    @staticmethod
    def _get_client():
        # Declared the environment variable in this way to ensure it works correctly inside LLm not working
        """Returns the appropriate LLM based on the workflow configuration"""
        if config.LLM_PROVIDER.lower() == "azure":
            return AzureOpenAI(
                azure_deployment=config.AZURE_OPENAI_DEPLOYMENT_NAME,
                azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
                api_version=config.AZURE_OPENAI_API_VERSION,
            )
        # elif config.LLM_PROVIDER.lower() == "ollama":
        #     return ChatOllama(model=config.OLLAMA_MODEL_NAME, base_url=config.OLLMA_BASE_URL)

    @staticmethod
    def _get_deploymnet_cfg():
        deployments = [
            {
                "name": config.AZURE_OPENAI_DEPLOYMENT_NAME,
                "model": config.AZURE_OPENAI_MODEL_NAME,
                "version": config.AZURE_OPENAI_MODEL_VERSION,
                "capacity": config.AZURE_OPENAI_CAPACITY,
            }
        ]
        return deployments

    def _get_or_create_deployments(self, deployments):
        for deployment in deployments:
            if not self._deployment_exists(deployment["name"], deployment["capacity"]):
                self._create_deployment(
                    deployment["name"], deployment["model"], deployment["version"], deployment["capacity"]
                )
            else:
                logger.debug(f"Deployment {deployment['name']} already exists")

    def _deployment_exists(self, deployment_name, capacity):
        """
        Check if a deployment already exists.
        """
        try:
            deploy_json = self._cog_acc.deployments.get(
                config.AZURE_OPENAI_RESOURCE_GROUP, config.AZURE_OPENAI_ACCOUNT, deployment_name
            ).serialize()
            logger.info(f"Have found OpenAI deployment {deploy_json}")
            if deploy_json["sku"]["capacity"] != capacity:
                logger.info(f"Still need to update parameters. Forcing re-creation for {deployment_name}")
                return False

            return True
        except ResourceNotFoundError:
            return False

    def _create_deployment(self, deployment_name, model, version, capacity):
        """
        Create a new deployment. This is not fast.
        """
        sku = "GlobalStandard" if model == "gpt-4o" else "Standard"
        deployment_params = {
            "properties": {
                "model": {"format": "OpenAI", "name": model, "version": version},
            },
            "sku": {
                "name": sku,
                "capacity": capacity,
            },
            "raiPolicyName": "DefaultV2",
        }
        logger.info(f"Creating deployment: {deployment_params}")
        try:
            poller = self._cog_acc.deployments.begin_create_or_update(
                config.AZURE_OPENAI_RESOURCE_GROUP, config.AZURE_OPENAI_ACCOUNT, deployment_name, deployment_params
            )
            poller.result()
        except HttpResponseError as e:
            logger.error(f"Failed creating deployment {deployment_name} HttpResponseError with {e}")
            raise e

        logger.info(f"Creating deployment {deployment_name} complete")


# TODO - merge the clients
llm_client = LLMClient(redeploy=config.AZURE_OPENAI_DEPLOY)
