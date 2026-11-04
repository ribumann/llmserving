# export_worker Container Apps Job (T136): serializes a Result Report to CSV/JSON and
# uploads it to the `exports` blob container in `artifacts_storage`
# (infra/control/main.tf) using this job's own user-assigned managed identity.
#
# NOTE: build with the *repository root* as context, e.g.
#   docker build -f jobs/export_worker/Dockerfile -t llmserving-export-worker:latest .
FROM python:3.11-slim AS runtime

WORKDIR /app

COPY jobs/export_worker/requirements.txt ./requirements.txt
COPY jobs/common ./common
COPY jobs/export_worker/entrypoint.py ./entrypoint.py

RUN pip install --no-cache-dir -r requirements.txt

ENTRYPOINT ["python", "entrypoint.py"]
