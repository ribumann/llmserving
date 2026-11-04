# performance_worker Container Apps Job (T136): runs a concurrent load test against
# the deployed vLLM endpoint over the private VNet.
#
# NOTE: build with the *repository root* as context, e.g.
#   docker build -f jobs/performance_worker/Dockerfile -t llmserving-performance-worker:latest .
FROM python:3.11-slim AS runtime

WORKDIR /app

COPY jobs/performance_worker/requirements.txt ./requirements.txt
COPY jobs/common ./common
COPY jobs/performance_worker/entrypoint.py ./entrypoint.py

RUN pip install --no-cache-dir -r requirements.txt

ENTRYPOINT ["python", "entrypoint.py"]
