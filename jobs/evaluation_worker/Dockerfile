# evaluation_worker Container Apps Job (T136): runs golden-dataset/benchmark prompt
# cases against the deployed vLLM endpoint over the private VNet.
#
# NOTE: build with the *repository root* as context, e.g.
#   docker build -f jobs/evaluation_worker/Dockerfile -t llmserving-evaluation-worker:latest .
FROM python:3.11-slim AS runtime

WORKDIR /app

COPY jobs/evaluation_worker/requirements.txt ./requirements.txt
COPY jobs/common ./common
COPY jobs/evaluation_worker/entrypoint.py ./entrypoint.py

RUN pip install --no-cache-dir -r requirements.txt

ENTRYPOINT ["python", "entrypoint.py"]
