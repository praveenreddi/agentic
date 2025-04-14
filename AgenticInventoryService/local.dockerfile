FROM python:3.12-slim
COPY --from=datadog/serverless-init:1 /datadog-init /app/datadog-init

# Enable Datadog automatic instrumentation
# Ref: https://docs.datadoghq.com/serverless/azure_container_apps/
# RUN pip3 install --target /dd_tracer/python/ ddtrace
ENV DD_LOGS_ENABLED=true
ENV DD_TRACE_ENABLED=false
ENV DD_SERVICE=travel-agent-chatbot-service
ENV DD_APM_ENABLED=false
ENV DD_RUNTIME_METRICS_ENABLED=false

WORKDIR /usr/app

RUN apt update \
    && apt install --no-install-recommends -y gcc build-essential azure-cli \
    && apt clean

RUN pip3 install poetry \
    --trusted-host pypi.python.org \
    --trusted-host files.pythonhosted.org

# all we need
COPY agentic_inventory/ ./agentic_inventory
COPY README.md .
COPY agentic_inventory.conf.py .
COPY poetry.lock .
COPY pyproject.toml .


ENV POETRY_CACHE_DIR=/tmp/poetry_cache
# install poetry stuff and show installed packages for logging build artefacts checking
RUN poetry config virtualenvs.create false \
 && poetry config certificates.PyPI.cert false \
 && poetry config certificates.fpho.cert false \
 && poetry config certificates.github.cert false \
 && poetry install --no-interaction --no-ansi --only main \
 && rm -rf $POETRY_CACHE_DIR \
 && poetry show

 # certificate copy to container
COPY nscacert_combined.pem /tmp/nscacert_combined.pem
ENV REQUESTS_CA_BUNDLE=/tmp/nscacert_combined.pem
ENV SSL_CERT_FILE=/tmp/nscacert_combined.pem

EXPOSE 8080
# Needed to wrap the intended process w/ datadog agent so we start the agent up along w/ the service.
ENTRYPOINT ["/app/datadog-init"]
#CMD  ["poetry", "run", "gunicorn", "agentic_inventory.main:app", "-c", "agentic_inventory.conf.py"]
# TODO for dd-tracer
CMD  ["ddtrace-run", "poetry", "run", "gunicorn", "agentic_inventory.main:app", "-c", "agentic_inventory.conf.py"]
