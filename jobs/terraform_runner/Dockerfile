# terraform_runner Container Apps Job (T136): runs `terraform apply`/`destroy` against
# infra/demo (rg-llm-demo-{environmentId}) in isolation from FastAPI's request thread.
#
# Authenticates to Azure via this job's own user-assigned managed identity
# (AZURE_CLIENT_ID/ARM_SUBSCRIPTION_ID/ARM_TENANT_ID, set by infra/control/main.tf) - no
# service principal secret. Reports progress/completion to FastAPI's internal callback API
# using the same identity (jobs/common/callback_client.py).
#
# The `az` CLI (not just the azurerm provider's own MSI implementation) is required here:
# entrypoint.py's _ensure_azure_cli_auth() runs `az login --identity` and points the azurerm
# provider at Azure CLI auth (ARM_USE_CLI=true) instead of ARM_USE_MSI, working around a
# confirmed, still-open upstream bug (hashicorp/terraform-provider-azurerm#33001,
# hashicorp/go-azure-sdk#1217) where the provider's Go SDK never sends the
# `X-IDENTITY-HEADER` Container Apps' managed-identity sidecar requires, so the provider's own
# MSI auth always fails with 403 in this hosting context. Azure CLI's Python auth stack
# already handles Container Apps' identity convention correctly.
#
# NOTE: build with the *repository root* as context, e.g.
#   docker build -f jobs/terraform_runner/Dockerfile -t llmserving-terraform-runner:latest .
FROM python:3.11-slim AS runtime

ARG TERRAFORM_VERSION=1.9.8

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && curl -fsSL -o /tmp/terraform.zip \
        "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
    && unzip -o /tmp/terraform.zip -d /usr/local/bin terraform \
    && rm /tmp/terraform.zip \
    && apt-get purge -y unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY jobs/terraform_runner/requirements.txt ./requirements.txt
COPY jobs/common ./common
COPY jobs/terraform_runner/entrypoint.py ./entrypoint.py
# infra/demo is the actual Terraform module this job applies/destroys - baked in at build
# time (not mounted), matching how backend/Dockerfile used to bake in infra/azure before the
# Baseline Azure Pilot Architecture refactor moved that responsibility here.
COPY infra/demo ./infra/demo

RUN pip install --no-cache-dir -r requirements.txt azure-cli

ENTRYPOINT ["python", "entrypoint.py"]
