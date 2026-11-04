from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "Azure LLM Serving Demo Backend"
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/llmserving"
    database_echo: bool = False
    azure_subscription_id: str | None = None
    azure_tenant_id: str | None = None
    azure_client_id: str | None = None
    # Expected `aud` claim for a managed-identity bearer token calling the internal
    # orchestration callback API (contracts/api.md), e.g. an Entra ID app registration's
    # Application ID URI or client ID. Internal endpoints fail closed (503) when unset,
    # since that means no audience has been configured to validate against.
    internal_api_audience: str | None = None
    hf_token_passthrough_header: str = "X-HuggingFace-Token"
    auth_allowed_email_domains: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["example.com"]
    )
    auth_bypass_paths: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "/healthz",
            "/openapi.json",
            "/docs",
            "/docs/oauth2-redirect",
            "/redoc",
            # Not part of the operator-facing SSO surface (contracts/api.md Internal
            # Orchestration Callback API): authenticated separately, via managed-
            # identity bearer tokens validated by src/api/internal_auth.py, never by
            # the browser-session headers this SSO middleware checks for.
            "/internal",
        ]
    )
    # Origins allowed to call this API from a browser (the operator frontend's own
    # origin, e.g. https://llm-frontend.<region>.azurecontainerapps.io). Left empty
    # by default (no cross-origin browser access) for local/test runs; infra/control
    # sets this as a Container App env var to the deployed frontend's FQDN.
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Set as Container App env vars by infra/control/main.tf (T140). Read by
    # container_jobs.py's dispatch_job() to pre-dispatch the model_deployment
    # Container Apps Job directly from AzureDeployer - the one workflow type
    # FastAPI dispatches itself rather than through the Durable Functions
    # orchestration app's own dispatch_job activity (see
    # providers/azure/functions_client.py's module docstring for why).
    container_apps_resource_group: str | None = None
    job_name_model_deployment: str | None = None
    vllm_image: str = "vllm/vllm-openai:latest"
    ollama_base_url: str = "http://localhost:11434"
    lm_eval_path: str = "lm_eval"
    llmperf_path: str = "llmperf"
    adapter_contract_version: str = "2026-08-19"
    # HTTP timeout for real-time vLLM engine calls (prompt submissions, health/metrics
    # checks) made by VllmEngineAdapter. Prompt completions routinely take well past a
    # few seconds — especially for larger and/or quantized models, and reasoning models
    # (e.g. Qwen3) that emit long "<think>" traces before the final answer — so this
    # must be generous enough to cover real inference latency, not just network RTT.
    vllm_prompt_timeout_seconds: float = 120.0

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator(
        "auth_allowed_email_domains",
        "auth_bypass_paths",
        "cors_allowed_origins",
        mode="before",
    )
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Parse a settings field documented as plain CSV (e.g. "a,b,c").

        Also tolerates a JSON-array-encoded string (e.g. '["a", "b"]'), since that's an
        easy mistake to make when setting these via App Service app settings or a .env
        file (both of which only support flat strings) — without this, a JSON-looking
        value would be comma-split verbatim into garbage entries like '["a"' and '"b"]'.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                try:
                    decoded = json.loads(stripped)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, list):
                    return [str(item).strip() for item in decoded if str(item).strip()]
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
