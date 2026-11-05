# performance_worker Container Apps Job (T136): runs a concurrent load test against
# the deployed vLLM endpoint over the private VNet.
#
# NOTE: build with the *repository root* as context, e.g.
#   docker build -f jobs/performance_worker/Dockerfile -t llmserving-performance-worker:latest .
FROM python:3.11-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY jobs/performance_worker/requirements.txt ./requirements.txt
COPY jobs/common ./common
COPY jobs/performance_worker/entrypoint.py ./entrypoint.py
COPY backend/src/__init__.py ./src/__init__.py
COPY backend/src/performance/__init__.py ./src/performance/__init__.py
COPY backend/src/performance/llmperf_runner.py ./src/performance/llmperf_runner.py

# Package the exact API runner/tool for parity validation; entrypoint/routing is unchanged.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps --ignore-requires-python \
        "llmperf @ git+https://github.com/ray-project/llmperf.git@f1d6bed47e4501b0e371082b41601b59ab55269f" \
    && pip install --no-cache-dir "numpy<2.3" ray pandas "transformers>=4.1" tqdm litellm

# Upstream does not install its root CLI or prompt data; use the same pinned files as the API.
RUN LLMPERF_PKG_DIR="$(python -c 'import llmperf, os; print(os.path.dirname(llmperf.__file__))')" \
    && curl -fsSL -o "${LLMPERF_PKG_DIR}/token_benchmark_ray.py" \
        https://raw.githubusercontent.com/ray-project/llmperf/f1d6bed47e4501b0e371082b41601b59ab55269f/token_benchmark_ray.py \
    && curl -fsSL -o "${LLMPERF_PKG_DIR}/sonnet.txt" \
        https://raw.githubusercontent.com/ray-project/llmperf/f1d6bed47e4501b0e371082b41601b59ab55269f/src/llmperf/sonnet.txt

ENTRYPOINT ["python", "entrypoint.py"]
