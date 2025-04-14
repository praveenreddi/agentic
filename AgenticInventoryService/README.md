# Introduction
TODO: Give a short introduction of your project. Let this section explain the objectives or the motivation behind this project.

## Architecture

See (Design)[./docs/Design.md]

# Getting Started

This service was implemented
using [OneSystem Service Template](https://hiltongrandvacations.visualstudio.com/HGVC/_wiki/wikis/HGVC.wiki/918/OneSystem-Template).

This is *heavily* modified to be a Python service as opposed to .NET, since we use lots of LLM related libraries.

## Option 1 - Using a DevContainer (Requires Docker)

This project is set up to use a DevContainer. DevContainers are a combination of the `.devcontainer/devcontainer.json`
file, Docker, and your IDE.
When you spin up a dev container using your IDE, it will create a container with all the developer dependencies in an
isolated environment, including all the tools you need, like Poetry and the correct Python version, and then attach your
IDE to it.
This way our dev environments are consistent and repeatable.

*However*, it is very hard (not worth it) to actually get this set up inside a VDI, so if you are using a VDI and not
local hardware for development, then you should use option 2...

## Option 2 - Manual Setup

Use this option if you don't have access to docker, or docker isn't installing for you (like on a VDI).
The devcontainer will set up these steps for you.

### Install Python

Current version set up as of this writing is Version 3.12.7, however you can always look for the specific version to use
that's configured in `pyproject.toml`.

### Install Poetry

You'll need to install [Poetry](https://python-poetry.org/). Poetry is used as the project's package manager and virtual
environment manager, so take a look at the docs for installation instructions and setup instructions.

From `./`, run `poetry install` to install all the dependencies.

Check the docs to set up your python environment using `poetry env` commands.

### MacOS specifics

Given we have lots of endpoints agents you may find SSL issues with poetry and python in general. Run the following to
fix it

```shell
poetry config certificates.PyPI.cert false
#poetry config certificates.fpho.cert false
poetry config certificates.fpho.cert false
```

## Running the project locally

For basic things run `poetry run python -m uvicorn run` from the command line to spin up the API.
Or if you want to test more things, run `./run.sh` with either `fast_api` or `gunicron`
If you want to test it locally run './run.sh fastapi' in one terminal and in the second terminal run './run.sh streamlit'

## First run

Before running the app, make sure you have done `az login` and logged into `HGV-IT-ArchPoC` subscription.
This is necessary to make sure the Azure OpenAI client runs locally as is relays on Az CLI login method,

See [ExampleEnv](EXAMPLE.env) and copy it over your [private env](.env) for running locally.

### SSL cert issues

1) When running locally you may find SSL cert issues due to MITM NetScope. For that you need to export your Netskope
   combined cert.

Here are the instruction for MacOS.

```shell
# Netskope SSL Interception settings
security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain \
    /Library/Keychains/System.keychain >/tmp/nscacert_combined.pem &&
    sudo cp /tmp/nscacert_combined.pem /Library/Application\ Support/Netskope/STAgent/download

export REQUESTS_CA_BUNDLE='/Library/Application Support/Netskope/STAgent/download/nscacert_combined.pem'
export SSL_CERT_FILE='/Library/Application Support/Netskope/STAgent/download/nscacert_combined.pem'
```

2) AZ OpenAI is blocked by firewalls (Netskope)

Here is the one already setup with extra DNS - just use your deployment.
Caution: only use for proper Chatbot local development. If need an new cognitive account go to OneSystem_IAB/dev/ai-ml
and work with ICA folks.

```shell
#AZURE_OPENAI_ENDPOINT=https://ryanaipoc.openai.azure.com/openai/deployments/...
# DNS proxy set up by IAC
AZURE_OPENAI_ENDPOINT=https://ryanaipoc-ai.apps.dev.onegrandvacation.com/openai/deployments/...
```

### Running tests locally

To run integration/automation tests, run `poetry run pytest` or `./run.sh test` from the command line.
Make sure your [private env](.env) is set correctly.

### Using local bot console

You can use local console to bots in all environments via
`./run.sh console --env <local|dev|qat|stg|prd> [--id member_id] [--session-id <reuse_session>]`.
For that, copy `EXAMPLE.console.config` to `console.config` and enter the Azure subscription keys there.

## Azure resources

`AgenticInventory` service uses following resources in Azure:

- KV - `kv-usw3-<env>-ai-inventory`, [AZ Dev link](https://portal.azure.com/?feature.tokencaching=true&feature.internalgraphapiversion=true#@hgv.com/resource/subscriptions/20c113c3-a365-4189-b651-b2f1e4f4425d/resourceGroups/RG-USW3-DEV-AI-ML/providers/Microsoft.KeyVault/vaults/kv-usw3-dev-ai-intentory/overview)
  - Cosmos - `cosmos-usw2-<env>-ai-inventory-db`, [AZ Dev Link](https://portal.azure.com/?feature.tokencaching=true&feature.internalgraphapiversion=true#@hgv.com/resource/subscriptions/20c113c3-a365-4189-b651-b2f1e4f4425d/resourceGroups/RG-USW3-DEV-AI-ML/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-usw2-dev-ai-inventory-db/Connection%20strings)
  - OpenAI - `cog-usw3-<dev>-ai-inv`, [AZ Dev Link](https://portal.azure.com/?feature.tokencaching=true&feature.internalgraphapiversion=true#@hgv.com/resource/subscriptions/20c113c3-a365-4189-b651-b2f1e4f4425d/resourceGroups/RG-USW3-DEV-AI-ML/providers/Microsoft.CognitiveServices/accounts/cog-usw3-dev-ai-inv/cskeys)
  - EnterpriseApps:
    - PRD = AgenticInventoryApp, [AZ Link](https://portal.azure.com/#view/Microsoft_AAD_IAM/ManagedAppMenuBlade/~/Users/objectId/541afe2a-8b43-4c9e-99cc-7d1e2f227121/appId/ad2e3844-fa38-4991-9dc7-44ecab81e1cf)
    - NonPRD = AgenticInventoryAppNPD [AZ Link](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationMenuBlade/~/Authentication/appId/6466ee5d-8bd0-4b6d-b381-e78da2a635b4)
  - DNS names deploy via [TF Repo Link](https://dev.azure.com/HiltonGrandVacations/OneVision/_git/OneSystem_IaC_AIML)
    - https://ai-inventory.apps.dev.onegrandvacation.com/
    - https://ai-inventory.apps.qat.onegrandvacation.com/
    - https://ai-inventory.apps.stg.onegrandvacation.com/
    - https://ai-inventory.apps.onegrandvacation.com/

Pipeline libraries:
 - [OneSystem-agentic-inventory-DEV](https://hiltongrandvacations.visualstudio.com/OneVision/_library?itemType=VariableGroups&view=VariableGroupView&variableGroupId=1919&path=OneSystem-agentic-inventory-DEV)
 - [OneSystem-agentic-inventory-QAT](https://hiltongrandvacations.visualstudio.com/OneVision/_library?itemType=VariableGroups&view=VariableGroupView&variableGroupId=1920&path=OneSystem-agentic-inventory-QAT)
 - [OneSystem-agentic-inventory-STG](https://hiltongrandvacations.visualstudio.com/OneVision/_library?itemType=VariableGroups&view=VariableGroupView&variableGroupId=1921&path=OneSystem-agentic-inventory-STG)
 - [OneSystem-agentic-inventory-PRD](https://hiltongrandvacations.visualstudio.com/OneVision/_library?itemType=VariableGroups&view=VariableGroupView&variableGroupId=1922&path=OneSystem-agentic-inventory-PRD)


## Load Testing

The service includes a comprehensive stress testing framework that allows testing the system under various load conditions. The stress testing framework is located in the `tests/stress` directory.

### Running Stress Tests

To run stress tests, use the following command:
```bash
./run.sh stress_test [short|medium|long|full]
```

Available test durations:
1. **short**: 60-second test with 10 RPS
   - 10 concurrent users
   - 10-second ramp-up time
   - Suitable for quick performance checks

2. **medium**: 5-minute test with 20 RPS
   - 20 concurrent users
   - 30-second ramp-up time
   - Good for moderate load testing

3. **long**: 10-minute test with 30 RPS
   - 30 concurrent users
   - 60-second ramp-up time
   - Comprehensive load testing

4. **full**: 24-hour test with 10 RPS
   - 100M token limit (test will stop if either limit is reached)
   - 5-minute ramp-up time
   - Complete system endurance test
   - Tests all endpoints including session management and inventory queries
   - Suitable for production-like load testing
   - Test will automatically stop when either:
     - 24 hours have elapsed, OR
     - 100 million tokens have been processed
   - Reports will indicate which limit was reached

### Test Configuration

Each test scenario includes:
- Session creation and management
- Inventory queries for Grand Californian Hotel
- Concurrent user simulation
- Gradual load increase (ramp-up)
- Token usage monitoring
- Response time tracking

### Test Reports

Stress test results are automatically generated and include:
- Response times and latency distributions
- Success/failure rates
- Error distributions
- System resource usage
- Token consumption metrics

Reports are saved in the `tests/stress/reports` directory with timestamps.

### Performance Thresholds

The system monitors the following thresholds during stress tests:
- Success rate: 99% minimum
- P95 latency: 2 seconds maximum
- Server memory usage: 1024MB maximum
- Server CPU usage: 80% maximum
- Error rate: 1% maximum
- Minimum RPS: 10 requests/second
- Maximum latency: 5 seconds per request

### Best Practices

1. Start with the short test to verify basic functionality
2. Use medium test for regular performance validation
3. Run long test for comprehensive load testing
4. Monitor system resources during test execution
5. Review test reports for performance bottlenecks

## CI/CD

The `merge-validation.yml` pipeline will run to execute quality gate checks for new Pull Requests.
The `azure-pipelines.yml` is the main build & release pipeline, it runs when commit is pushed to `main` - typically, a
merge commit once a PR is approved and merged.

> Refer
>
to [OneSystem/Pipelines/Container App/README.md](https://hiltongrandvacations.visualstudio.com/OneVision/_git/OneSystem?path=/Pipelines/Container%20App)
>
and [OneSystem Template - Deployment](https://hiltongrandvacations.visualstudio.com/HGVC/_wiki/wikis/HGVC.wiki/937/Deployment)
> for more information about ci/cd pipelines for this project type.

### Building the dockerfile locally

The python service runs inside a docker container in Azure, so many times it's useful to be able to build and run this
container locally to ensure everything works as expected without having to wait on Azure DevOps builds and deployments.

from the root directory (where the `dockerfile` is):
 - To build the docker image, run  `./run.sh build`
   - NOTE: SSL issues with corp NetScope. To avoid the SSL certificate issues,
     we need to copy the certificate bundle to container.
     Its typically found here `Library/Application\ Support/Netskope/STAgent/download/nscacert_combined.pem`,
     copy this to project root directory.
 - To run it locally, run `./run.sh run`

The .env and console.log files are shared via email.
Api Exposure: http://0.0.0.0:8080/api/health .
You can chat with the bot using a postman collection or `./run.sh console`

## ML Inference endpoint

* Dev Endpoint : https://adb-1306636930224325.5.azuredatabricks.net/model/SVR/3/invocations
* OpenAPI spec : [ML Inference](AzureAPI/ml_inference_swagger_specv1.openapi.json)

#### ML API consumption

#### Input
It expects a json in the following format. It needs a segment_code, pm_unit_type_id and num_days which the number of days to forecast.

* Allowed values
- segment_code - All the segment codes model trained on
- pm_unit_type_id - All the pm_unit_codes model trained on
- start_ts - Forecast start date. date should be formatted to string type "MM-DD-YYYY"
- num_days - [1, 32), should be non negative number

Single feed forecast
```json
{"dataframe_split": {
   "index": [0],
   "columns": ["segment_code", "pm_unit_type_id", "num_days", "start_ts"],
   "data": [["WS", "16511", "3", "06-30-2025"]]
}}
```
Multiple feed forecast
```json
{"dataframe_split": {
   "index": [0, 1],
   "columns": ["segment_code", "pm_unit_type_id", "num_days", "start_ts"],
   "data": [["WS", "16511", "3", "06-30-2025"], ["FW", "10139", "3", "06-30-2025"]]
}}
```
#### output:
* It returns a json with the predictions in the following format

```json
{"predictions": {
   "GR_15753": {
      "prediction":{"1741737600000":0.0,"1741824000000":0.0,"1741910400000":0.0,"1741996800000":0.0}
   },
   "RMK_72672": {
      "prediction":{"1741737600000":0.0,"1741824000000":0.0,"1741910400000":0.0,"1741996800000":0.0}
   }
}}
```
#### Out of ordinary case
* if forecast is requested for segment/pm_unit_type_id which the model havent seen before, it will throw error with the corresponding segment code.

```json
{"predictions": {
   "error": ""GR1573""}
}
```
#### Bad input format
* Bad input format cases will lead to 4xx errors

```json
{"error_code": "BAD_REQUEST",
 "message": "The input must be a JSON dictionary with exactly one of the input fields..."}
```

## ML API High fidelity model endpoint.
* It provides 2 weeks of forecast from the current day. Takes roughly 5 seconds to respond.
* Dev Endpoint : https://adb-1306636930224325.5.azuredatabricks.net/model/lgb/2/invocations
* OpenAPI spec : [ML Inference](AzureAPI/ml_inference_swagger_specv1.openapi.json)

## Inputs
* Allowed values
- segment_code - All the segment codes model trained on
- pm_unit_type_id - All the pm_unit_codes model trained on
```json
{"dataframe_split": {"index": [0, 1], "columns": ["segment_code", "pm_unit_type_id"], "data": [["WS", "11608"], ["AD", "121041"]]}}
```
## output
```json
{'predictions': {'WS_11608': '{"prediction":{"1743465600000":7.0,"1743552000000":7.0,"1743638400000":9.0,"1743724800000":10.0,"1743811200000":9.0,"1743897600000":10.0,"1743984000000":11.0,"1744070400000":15.0,"1744156800000":11.0,"1744243200000":9.0,"1744329600000":9.0,"1744416000000":10.0,"1744502400000":8.0,"1744588800000":7.0}}',
  'AD_121041': '{"prediction":{"1743465600000":0.0,"1743552000000":0.0,"1743638400000":0.0,"1743724800000":0.0,"1743811200000":0.0,"1743897600000":0.0,"1743984000000":0.0,"1744070400000":0.0,"1744156800000":0.0,"1744243200000":0.0,"1744329600000":0.0,"1744416000000":0.0,"1744502400000":0.0,"1744588800000":0.0}}'}}
```



# Contribute
Refer to [Source Control for OneSystem](https://hiltongrandvacations.visualstudio.com/HGVC/_wiki/wikis/HGVC.wiki/979/Source-Control-for-ONE-SYSTEM)
