# Contracts: Inference Engine Interface

**Input**: FR-013, FR-014, FR-015, FR-026 in [spec.md](../spec.md)

Internal interface that all inference-engine-specific serving/generation logic sits behind. Two
engines are implemented: **vLLM** (the primary v1 path, selected in `research.md` Section 1) and
**Ollama** (User Story 7's local-only engine, `backend/src/engines/ollama/adapter.py`, serving small
Qwen checkpoints on the presenter's own machine with no Azure dependency). The domain model,
evaluation layer, and comparison logic depend only on this interface, not either engine's native API
(FR-014). Adding a second engine or a multi-server deployment profile later must not require
redefining existing experiment records (FR-015).

## Interface

```text
InferenceEngineAdapter:
  describeSettings() -> SettingsSchema
    # Enumerates presenter-controllable serving + generation settings and their visible
    # defaults, so Inference Configuration never hides a default (FR-013).

  deploy(modelConfig, inferenceConfig, targetEnvironment) -> DeploymentHandle
    # Loads the checkpoint referenced by modelConfig and applies inferenceConfig.
    # MUST NOT report ready until the engine's own health signal is green (FR-016, FR-017).

  getHealth(deploymentRevisionId) -> HealthStatus
    # Health/error/resource information exposed for the active deployment (constitution
    # principle III; FR-017).

  submitPrompt(deploymentRevisionId, prompt) -> PromptResult
    # Returns response text, timing breakdown (including TTFT and inter-token timing inputs),
    # and errors (FR-018, FR-026).

  runPerformanceWorkload(deploymentRevisionId, workload) -> PerformanceMetricsStream
    # Streams/accumulates TTFT, inter-token latency, end-to-end latency, throughput, failures,
    # and accelerator utilization when available, with units and distribution data sufficient to
    # compute p50/p95 (FR-025, FR-026, FR-027, FR-057).

  cancel(operationId) -> CancellationAck
    # Idempotent: repeated calls for the same operation do not alter already-recorded
    # diagnostics or create duplicate cancellation records (FR-054).
```

## Contract Rules

- `describeSettings()` output is the single source of truth for what an `Inference Configuration`
  may contain; the web app never hardcodes engine-specific settings outside this contract.
- Accelerator utilization is reported "when available" — the adapter MUST label utilization data
  as unavailable rather than fabricate a value if the engine or host cannot supply it (FR-026,
  Edge Case: "Monitoring data is partial or unavailable").
- Every call emits a per-operation timestamped event log entry regardless of whether the v1 UI
  surfaces it, per FR-062.
- The adapter is stateless with respect to the domain model: it never persists `Experiment Run` or
  `Result Report` records itself; the backend's `evaluation`/`performance` layers own persistence
  using the adapter's returned data.
- Per User Story 10, for the Azure/vLLM path `deploy()` and `runPerformanceWorkload()` execute inside
  an isolated Container Apps Job (`model_deployment` / `performance_worker`, FR-078), not inside
  FastAPI; any Hugging Face credential `deploy()` needs is passed into that job process only and
  held in memory for the call's duration (FR-082/FR-083). The job reports results back through the
  internal callback API (contracts/api.md) using the same correlation ID as the dispatching
  `Orchestration Workflow`.

## Engine Selection

The primary engine implementing this interface is **vLLM** (`vllm/vllm-openai`, Apache 2.0), selected
in `research.md` Section 1 after comparing self-hosted serving frameworks (vLLM, TGI, Triton +
TensorRT-LLM, SGLang, llama.cpp/Ollama) against model support, accelerator support, performance
features, operability, extensibility, licensing, project health, and Azure suitability. The
adapter targets vLLM's native OpenAI-compatible `/v1/chat/completions` and `/v1/completions`
endpoints and its native `/metrics`/`/health` endpoints for `getHealth`.

A second engine, **Ollama**, implements the same interface for User Story 7's local/non-Azure demo
path (`backend/src/engines/ollama/adapter.py`), targeting Ollama's OpenAI-compatible
`/v1/chat/completions` endpoint. Ollama does not expose an accelerator-utilization metrics endpoint,
so `runPerformanceWorkload` reports utilization as unavailable rather than fabricating a value
(FR-026, per the Contract Rules above).
