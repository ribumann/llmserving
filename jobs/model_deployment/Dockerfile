# model_deployment Container Apps Job (T136/T137): starts vLLM on the demo GPU VM via
# Azure VM Run Command using this job's own user-assigned managed identity
# (ARM_USE_MSI/ARM_SUBSCRIPTION_ID/ARM_TENANT_ID, set by infra/control/main.tf).
#
# NOTE: build with the *repository root* as context, e.g.
#   docker build -f jobs/model_deployment/Dockerfile -t llmserving-model-deployment:latest .
FROM python:3.11-slim AS runtime

WORKDIR /app

COPY jobs/model_deployment/requirements.txt ./requirements.txt
COPY jobs/common ./common
COPY jobs/model_deployment/entrypoint.py ./entrypoint.py

RUN pip install --no-cache-dir -r requirements.txt

ENTRYPOINT ["python", "entrypoint.py"]
