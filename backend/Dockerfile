# FastAPI control-plane backend for the Azure LLM Serving Demo.
#
# Runs as an Azure Container App (see infra/control/main.tf's azurerm_container_app.backend),
# authenticating to Azure via its user-assigned managed identity (ARM_USE_MSI/ARM_SUBSCRIPTION_ID/
# ARM_TENANT_ID). No `az` CLI is installed or required.
#
# NOTE: as of the Baseline Azure Pilot Architecture refactor (Phase 3), this container no longer
# shells out to `terraform` itself — provisioning/teardown now dispatch to the isolated
# `terraform_runner` Container Apps Job (jobs/terraform_runner) via the Durable Functions
# orchestrator, instead of running Terraform in-process here (contracts/provider-interface.md
# Azure Implementation Notes). The Terraform binary install and infra/azure bake-in this image
# used to require (back when AzureProvisioner ran `terraform apply` synchronously in a background
# thread against the now-removed infra/azure module) have been removed accordingly.
FROM python:3.11-slim AS runtime

# curl is only needed for the HEALTHCHECK below (not for app logic). build-essential/g++
# are needed to build native extensions pulled in by the "evaluation" extra below. git is
# needed by pip to fetch the "llmperf" dependency, which is only published on GitHub (the
# PyPI package of the same name is an unrelated placeholder - see pyproject.toml).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl build-essential git \
    && rm -rf /var/lib/apt/lists/*

# NOTE: build with the *repository root* as context (not backend/), e.g.
#   docker build -f backend/Dockerfile -t llmserving-backend:latest .
WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/README.md ./README.md
COPY backend/src ./src
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
COPY backend/docker-entrypoint.sh ./docker-entrypoint.sh

# --ignore-requires-python: upstream llmperf declares "requires-python < 3.11" (stale
# metadata from when it was authored); its actual code runs fine on 3.11, verified via
# live import/exec testing against this image.
#
# llmperf is installed separately (--no-deps) from its git source (see comment in
# pyproject.toml's "evaluation" extra for why), followed by only the runtime libraries
# token_benchmark_ray.py actually imports (ray, pandas, transformers, tqdm, litellm).
# This deliberately skips upstream's unrelated/heavy extras (awscli, boto3,
# google-cloud-aiplatform, seaborn) and its stale "pydantic<2.5" pin, which would
# otherwise conflict with our own pydantic>=2.8 requirement.
RUN pip install --no-cache-dir -e ".[evaluation]" \
    && pip install --no-cache-dir --no-deps --ignore-requires-python \
        "llmperf @ git+https://github.com/ray-project/llmperf.git@f1d6bed47e4501b0e371082b41601b59ab55269f" \
    && pip install --no-cache-dir ray pandas "transformers>=4.1" tqdm litellm \
    && chmod +x ./docker-entrypoint.sh

# ray-project/llmperf's actual CLI entrypoint, token_benchmark_ray.py, lives at the
# repository root, NOT inside the installed "llmperf" package directory - and the repo
# declares no console_scripts/py_modules for it, so `pip install` above never installs it.
# Likewise, sonnet.txt (a package data file token_benchmark_ray.py reads at runtime to
# build prompts) isn't picked up by the sdist/wheel build either. src/performance/
# llmperf_runner.py expects the entrypoint script next to the installed package, so fetch
# both files (same pinned commit) straight into that directory.
RUN LLMPERF_PKG_DIR="$(python -c 'import llmperf, os; print(os.path.dirname(llmperf.__file__))')" \
    && curl -fsSL -o "${LLMPERF_PKG_DIR}/token_benchmark_ray.py" \
        https://raw.githubusercontent.com/ray-project/llmperf/f1d6bed47e4501b0e371082b41601b59ab55269f/token_benchmark_ray.py \
    && curl -fsSL -o "${LLMPERF_PKG_DIR}/sonnet.txt" \
        https://raw.githubusercontent.com/ray-project/llmperf/f1d6bed47e4501b0e371082b41601b59ab55269f/src/llmperf/sonnet.txt

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["./docker-entrypoint.sh"]
